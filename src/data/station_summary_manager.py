"""Manager for station summary (history) data.

The summary is a Gantt-style timeline: one row per channel (from ``icm.cells``)
with bars built from episodes in ``icm.channel_history``. Reads via ``SELECT``;
``log_channel_usage`` writes via ``usp_history_insert`` / ``usp_history_update``.
"""

from datetime import datetime, timedelta, date
from math import ceil

from src.data.db import get_db, DatabaseError, to_text, to_param
from src.data.enums import CellStatus
from src.data.projects_manager import ProjectsManager

# Columns on icm.channel_history.
HISTORY_COLUMNS = [
    "id", "channel", "project_id", "current_owner", "assembled_by", "status",
    "start_date", "start_hour", "end_date", "expected_end_date", "cathode",
    "anode", "data_filename", "original_data_filename", "added_water_b",
    "comments", "separator",
]


class StationSummaryManager:
    """Manages the station summary / channel history data."""

    DATE_FORMAT = "%Y-%m-%d"

    # Statuses for an ongoing experiment: its bar keeps growing to the current
    # date instead of freezing at the end_date stored when it was last saved.
    ONGOING_STATUSES = ("in use",)

    def __init__(self, db=None):
        self._db = db or get_db()
        # Project colors drive the bar colors in the timeline.
        self.projects_manager = ProjectsManager(self._db)

    # ----------------------------------------------------------- Public API
    def get_channel_history(self) -> list:
        """Return ``[{"channel", "status", "episodes": [episode, ...]}, ...]``.

        ``status`` is the channel's current cell status (drives the row tint in
        the timeline). All channels from ``icm.cells`` are included (empty
        episode list when a channel has no history yet).
        """
        cell_rows = self._db.fetch_all(
            "SELECT channel, status FROM icm.cells ORDER BY id"
        )

        columns = ", ".join(HISTORY_COLUMNS)
        episode_rows = self._db.fetch_all(
            f"SELECT {columns} FROM icm.channel_history "
            "ORDER BY channel, start_date, id"
        )

        by_channel: dict[str, list] = {}
        for r in episode_rows:
            entry = {k: to_text(r.get(k)) for k in HISTORY_COLUMNS}
            episode = self._normalize_episode(entry)
            if episode is not None:
                by_channel.setdefault(entry["channel"], []).append(episode)

        rows = []
        for r in cell_rows:
            channel = to_text(r.get("channel"))
            if not channel:
                continue
            rows.append({
                "channel": channel,
                "status": to_text(r.get("status")),
                "episodes": by_channel.get(channel, []),
            })
        return rows

    def get_date_range(self):
        """Return ``(min_date, max_date)`` spanning all episodes, or ``None``.

        ``max_date`` also covers expected_end_date so the dashed planned-end
        extension isn't clipped by the axis.
        """
        row = self._db.fetch_row(
            "SELECT (SELECT MIN(start_date) FROM icm.channel_history) AS mn, "
            "(SELECT MAX(v.d) FROM icm.channel_history h "
            " CROSS APPLY (VALUES (h.end_date), (h.expected_end_date)) v(d)) AS mx"
        )
        if not row or row.get("mn") is None or row.get("mx") is None:
            return None
        mn, mx = row["mn"], row["mx"]
        if isinstance(mn, datetime):
            mn = mn.date()
        if isinstance(mx, datetime):
            mx = mx.date()
        return mn, mx

    def get_statistics(self) -> dict:
        """Return ``{"total": n, "status_counts": {...}}`` from the live cells.

        Counts reflect each channel's *current* status in ``icm.cells`` — the
        source of truth — not the latest history episode. The latest episode can
        drift from reality when a channel changes status without a new history
        entry (e.g. it goes back to Available after a repair), which previously
        inflated counts such as "In repair" (15 shown vs. 6 actually in repair).
        """
        total_row = self._db.fetch_row("SELECT COUNT(*) AS n FROM icm.cells")
        total = int(total_row["n"]) if total_row and total_row.get("n") is not None else 0

        rows = self._db.fetch_all(
            "SELECT status, COUNT(*) AS n FROM icm.cells GROUP BY status"
        )
        raw: dict[str, int] = {}
        for r in rows:
            # A blank status means the cell is free, so fold it into Available.
            status = (to_text(r.get("status")) or "").strip() or "Available"
            raw[status] = raw.get(status, 0) + int(r.get("n") or 0)

        # Show the known statuses first (in enum order), then any legacy extras.
        status_counts: dict[str, int] = {}
        for status in CellStatus.values():
            if status in raw:
                status_counts[status] = raw.pop(status)
        status_counts.update(raw)

        return {"total": total, "status_counts": status_counts}

    def log_channel_usage(self, channel: str, row_data: dict) -> None:
        """Log a channel usage: insert a new episode or update the matching one.

        Matches an existing episode by data filename (or the original filename
        when it was renamed), mirroring the previous file-based behavior.
        """
        def field(*keys: str) -> str:
            for key in keys:
                value = row_data.get(key)
                if value not in (None, ""):
                    return str(value).strip()
            return ""

        # Available / In repair free the cell (they're cell states, not
        # experiments): finalize the active episode as "Test finished" and don't
        # log an in-progress update. Match by the pre-clear filename.
        if field("Status", "status").lower() in ("available", "in repair"):
            original = (row_data.get("__original_data_filename") or "").strip()
            self._finish_episode(
                channel, original or field("Data filename", "data_filename")
            )
            return

        start_date = self._parse_date(field("Start date", "start_date"))
        if start_date is None:
            return  # no start date yet — nothing to log

        try:
            start_hour = int(field("Start hour", "start_hour") or "0")
        except ValueError:
            start_hour = 0

        start_dt = datetime.combine(start_date, datetime.min.time()).replace(hour=start_hour)
        total_hours = int((datetime.now() - start_dt).total_seconds() // 3600)
        duration_days = max(1, ceil(total_hours / 24))
        end_date = start_date + timedelta(days=duration_days - 1)

        # Finishing a test stamps the actual end at today: the duration-based
        # end_date above can land a day early for short runs.
        if field("Status", "status").lower() == "test finished":
            end_date = date.today()

        filename = field("Data filename", "data_filename")
        original = (row_data.get("__original_data_filename") or "").strip()

        # Find the episode to update: by the original name if it was renamed/
        # cleared, otherwise by the current filename.
        if original and original != filename:
            existing_id = self._find_episode_id(channel, original)
        else:
            existing_id = self._find_episode_id(channel, filename)

        params = {
            "channel": channel,
            "project_id": to_param(field("Project ID", "project_id")),
            "current_owner": to_param(field("Current owner", "current_owner")),
            "assembled_by": to_param(field("Assembled by", "assembled_by")),
            "status": to_param(field("Status", "status")),
            "start_date": start_date.strftime(self.DATE_FORMAT),
            "start_hour": start_hour,
            "end_date": end_date.strftime(self.DATE_FORMAT),
            "expected_end_date": to_param(
                field("Expected end date", "expected_end_date")
            ),
            "cathode": to_param(field("Cathode", "cathode")),
            "anode": to_param(field("Anode", "anode")),
            "data_filename": to_param(filename),
            "original_data_filename": to_param(original or filename),
            "added_water_b": to_param(field("Added water by timing", "added_water_b")),
            "comments": to_param(field("Comments", "comments")),
            "separator": to_param(field("Separator", "separator")),
        }

        try:
            if existing_id is not None:
                self._db.exec_proc("usp_history_update", {"id": existing_id, **params})
            else:
                self._db.exec_proc("usp_history_insert", params, returns_id=True)
        except DatabaseError as e:
            print(f"Error logging channel usage: {e}")

    def update_episode(self, episode_id, values: dict) -> bool:
        """Update a history episode via ``usp_history_update``. False on failure.

        ``values`` is keyed by the proc's parameter names; empty strings become
        NULL and ``start_hour`` is coerced to an int.
        """
        params = {k: to_param(v) for k, v in values.items()}
        params["id"] = int(episode_id)
        if params.get("start_hour") is not None:
            try:
                params["start_hour"] = int(params["start_hour"])
            except (ValueError, TypeError):
                params["start_hour"] = None
        try:
            self._db.exec_proc("usp_history_update", params)
            return True
        except (DatabaseError, ValueError, TypeError) as e:
            print(f"Error updating episode: {e}")
            return False

    def delete_episode(self, episode_id) -> bool:
        """Delete one history episode by its id. Returns False on failure.

        Only removes the ``channel_history`` row; the live cell is untouched.
        """
        try:
            self._db.exec_proc("usp_history_delete", {"id": int(episode_id)})
            return True
        except (DatabaseError, ValueError, TypeError) as e:
            print(f"Error deleting episode: {e}")
            return False

    def remove_project_from_history(self, project_name: str) -> int:
        """No-op: the DB FK ``ON DELETE SET NULL`` clears the project from every
        history row automatically when the project is deleted."""
        return 0

    def rename_project_in_history(self, old_name: str, new_name: str) -> int:
        """No-op: the DB FK ``ON UPDATE CASCADE`` renames the project on every
        history row automatically when the project is renamed."""
        return 0

    # -------------------------------------------------------------- Helpers
    def _finish_episode(self, channel: str, filename: str) -> None:
        """Mark a channel's active episode 'Test finished'.

        Re-sends the episode's existing values through ``usp_history_update`` with
        only the status changed, so freeing the cell (which blanks its fields)
        doesn't wipe the history row.
        """
        episode_id = self._find_episode_id(channel, filename)
        if episode_id is None:
            return
        columns = ", ".join(HISTORY_COLUMNS)
        row = self._db.fetch_row(
            f"SELECT {columns} FROM icm.channel_history WHERE id = ?", (episode_id,)
        )
        if not row:
            return
        params = {k: to_param(to_text(row.get(k))) for k in HISTORY_COLUMNS}
        params["id"] = episode_id
        params["status"] = CellStatus.TEST_FINISHED.value
        # The experiment ended now: freeze the actual end_date at today (until
        # this, an ongoing bar was extended to today only at render time).
        params["end_date"] = date.today().strftime(self.DATE_FORMAT)
        # start_hour is a TINYINT param: coerce the string back to int (or None).
        if params.get("start_hour") is not None:
            try:
                params["start_hour"] = int(params["start_hour"])
            except (ValueError, TypeError):
                params["start_hour"] = None
        try:
            self._db.exec_proc("usp_history_update", params)
        except DatabaseError as e:
            print(f"Error finishing episode: {e}")

    def _find_episode_id(self, channel: str, filename: str):
        """Return the id of the latest episode with ``filename`` on ``channel``."""
        if not filename:
            return None
        row = self._db.fetch_row(
            "SELECT TOP 1 id FROM icm.channel_history "
            "WHERE channel = ? AND data_filename = ? ORDER BY id DESC",
            (channel, filename),
        )
        return int(row["id"]) if row else None

    def _normalize_episode(self, entry: dict):
        """Convert a raw history row into an episode with parsed dates."""
        if not isinstance(entry, dict):
            return None

        start = self._parse_date(
            (entry.get("Start date") or entry.get("start_date") or "").strip()
        )
        if start is None:
            return None

        end = self._parse_date((entry.get("end_date") or "").strip())
        if end is None:
            end = start  # fall back to a single-day bar

        # Planned end (optional): drives the dashed "expected" bar extension.
        expected_end = self._parse_date(
            (entry.get("expected_end_date") or "").strip()
        )

        cathode = (entry.get("Cathode") or entry.get("cathode") or "").strip()
        anode = (entry.get("Anode") or entry.get("anode") or "").strip()
        label = f"{cathode} | {anode}" if cathode or anode else ""

        project = (entry.get("Project ID") or entry.get("project_id") or "").strip()
        status = (entry.get("Status") or entry.get("status") or "").strip()

        # A finished test has a real end; its planned end is no longer relevant,
        # so drop it — no dashed extension for finished experiments.
        if status.lower() == "test finished":
            expected_end = None

        # Ongoing experiments run up to today: the stored end_date was frozen at
        # the day they were last saved, so extend the bar to the current date.
        # (Finished experiments keep their stored end.)
        if status.lower() in self.ONGOING_STATUSES:
            end = max(start, date.today())

        # In-repair bars always render red so they stand out, even when the
        # channel still has a project assigned (which would otherwise color the
        # bar by project, or grey when no project is set).
        if status.lower() == "in repair":
            color = CellStatus.color_for("In repair")
        else:
            color = self.projects_manager.color_for(project)

        return {
            "label": label,
            "status": status,
            "project": project,
            "color": color,
            "start": start,
            "end": end,
            "expected_end": expected_end,
            "data": dict(entry),
        }

    def _parse_date(self, text: str):
        """Parse a ``YYYY-MM-DD`` date string, returning ``None`` if invalid."""
        text = (text or "").strip()
        if not text:
            return None
        try:
            return datetime.strptime(text, self.DATE_FORMAT).date()
        except ValueError:
            return None
