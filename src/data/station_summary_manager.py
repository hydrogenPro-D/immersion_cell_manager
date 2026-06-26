"""Manager for station summary (history) data.

The summary is a Gantt-style timeline: one row per channel (from ``icm.cells``)
with bars built from episodes in ``icm.channel_history``. Reads via ``SELECT``;
``log_channel_usage`` writes via ``usp_history_insert`` / ``usp_history_update``.
"""

from datetime import datetime, timedelta
from math import ceil

from src.data.db import get_db, DatabaseError, to_text, to_param
from src.data.projects_manager import ProjectsManager

# Columns on icm.channel_history.
HISTORY_COLUMNS = [
    "id", "channel", "project_id", "current_owner", "assembled_by", "status",
    "start_date", "start_hour", "end_date", "cathode", "anode",
    "data_filename", "original_data_filename", "added_water_b",
    "comments", "separator",
]


class StationSummaryManager:
    """Manages the station summary / channel history data."""

    DATE_FORMAT = "%Y-%m-%d"

    def __init__(self, db=None):
        self._db = db or get_db()
        # Project colors drive the bar colors in the timeline.
        self.projects_manager = ProjectsManager(self._db)

    # ----------------------------------------------------------- Public API
    def get_channel_history(self) -> list:
        """Return ``[{"channel": str, "episodes": [episode, ...]}, ...]``.

        All channels from ``icm.cells`` are included (empty list when a channel
        has no history yet).
        """
        channels = [
            to_text(r.get("channel"))
            for r in self._db.fetch_all("SELECT channel FROM icm.cells ORDER BY id")
        ]

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
        for channel in channels:
            if not channel:
                continue
            rows.append({"channel": channel, "episodes": by_channel.get(channel, [])})
        return rows

    def get_date_range(self):
        """Return ``(min_date, max_date)`` spanning all episodes, or ``None``."""
        row = self._db.fetch_row(
            "SELECT MIN(start_date) AS mn, MAX(end_date) AS mx FROM icm.channel_history"
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
        """Return ``{"total": n, "status_counts": {...}}`` (by latest episode)."""
        rows = self.get_channel_history()
        status_counts: dict[str, int] = {}
        for row in rows:
            episodes = row["episodes"]
            if not episodes:
                continue
            latest = max(episodes, key=lambda ep: ep["start"] or datetime.min.date())
            status = latest["status"] or "Unknown"
            status_counts[status] = status_counts.get(status, 0) + 1
        return {"total": len(rows), "status_counts": status_counts}

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

    def remove_project_from_history(self, project_name: str) -> int:
        """No-op: the DB FK ``ON DELETE SET NULL`` clears the project from every
        history row automatically when the project is deleted."""
        return 0

    def rename_project_in_history(self, old_name: str, new_name: str) -> int:
        """No-op: the DB FK ``ON UPDATE CASCADE`` renames the project on every
        history row automatically when the project is renamed."""
        return 0

    # -------------------------------------------------------------- Helpers
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

        cathode = (entry.get("Cathode") or entry.get("cathode") or "").strip()
        anode = (entry.get("Anode") or entry.get("anode") or "").strip()
        label = f"{cathode} | {anode}" if cathode or anode else ""

        project = (entry.get("Project ID") or entry.get("project_id") or "").strip()
        color = self.projects_manager.color_for(project)

        status = (entry.get("Status") or entry.get("status") or "").strip()

        return {
            "label": label,
            "status": status,
            "project": project,
            "color": color,
            "start": start,
            "end": end,
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
