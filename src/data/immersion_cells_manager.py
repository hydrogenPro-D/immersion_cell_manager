"""Manager for immersion cells data and configuration.

Backed by the ``icm.cells`` table: reads via ``SELECT``, writes via the
``icm.usp_cell_*`` stored procedures. ``Duration`` is computed at runtime and is
not stored.
"""

import re
from datetime import datetime, timedelta

from src.data.db import get_db, DatabaseError, to_text, to_param, hours_text, hours_param
from src.data.projects_manager import ProjectsManager
from src.data.enums import CellStatus
from src.gui.widgets.field_types import FieldSpec, FieldType

# DB columns on icm.cells (in a stable order; ``duration`` is computed, not stored).
CELL_COLUMNS = [
    "channel", "status", "project_id", "current_owner", "assembled_by",
    "start_date", "start_hour", "expected_end_date", "cathode", "anode",
    "data_filename", "added_water_b", "comments", "separator",
]
# Added by migration 024; without it density/Fe come from the project.
CELL_COLUMNS_024 = ["density", "fe_ppm", "test_length_h"]
CELL_COLUMNS_026 = ["protocol"]


def expected_end(start_date: str, start_hour, test_length_h) -> str:
    """Start (date + hour) plus the test length, as YYYY-MM-DD; "" if incomplete."""
    hours = hours_param(test_length_h)
    if hours is None or not (start_date or "").strip():
        return ""
    try:
        start = datetime.strptime(start_date.strip()[:10], "%Y-%m-%d")
        start = start.replace(hour=int(start_hour or 0))
    except (ValueError, TypeError):
        return ""
    return (start + timedelta(hours=hours)).strftime("%Y-%m-%d")


class ImmersionCellsManager:
    """Manages immersion cells data and column configuration."""

    # Mapping of display names to column keys.
    COLUMNS_MAPPING = {
        "Channel": "channel",
        "Status": "status",
        "Project ID": "project_id",
        "Cathode": "cathode",
        "Anode": "anode",
        "Current owner": "current_owner",
        "Assembled by": "assembled_by",
        "Start date": "start_date",
        "Start hour": "start_hour",
        "Duration": "duration",
        "Test length [h]": "test_length_h",
        "Protocol": "protocol",
        "Expected end date": "expected_end_date",
        # Per cell; the editor fills in the project's values when a project is picked.
        "Density [g/L]": "density",
        "Fe [ppm]": "fe_ppm",
        "Data filename": "data_filename",
        "Added water by timing": "added_water_b",
        "Comments": "comments",
        "Separator": "separator"
    }

    # Per-column editor behaviour. Columns not listed default to plain text.
    FIELD_SPECS = {
        "Channel": FieldSpec(name="Channel", field_type=FieldType.TEXT, read_only=True),
        "Status": FieldSpec(
            name="Status",
            field_type=FieldType.CHOICE,
            choices=CellStatus.values(),
            color_resolver=CellStatus.color_for,
        ),
        "Start date": FieldSpec(
            name="Start date",
            field_type=FieldType.DATE,
        ),
        "Start hour": FieldSpec(
            name="Start hour",
            field_type=FieldType.TEXT,
            read_only=True,  # Read-only because it's edited via the date picker
        ),
        "Expected end date": FieldSpec(
            name="Expected end date",
            field_type=FieldType.DATE_ONLY,  # optional planned end (can be blank)
            read_only=True,  # start + test length
        ),
        "Duration": FieldSpec(
            name="Duration",
            field_type=FieldType.TEXT,
            read_only=True,  # Read-only because it's calculated at runtime
        ),
    }

    def __init__(self, db=None):
        """Initialize the immersion cells manager backed by the database."""
        self._db = db or get_db()
        # Projects are a configurable list shown as a dropdown in the editor.
        self.projects_manager = ProjectsManager(self._db)
        self._people = None  # names suggested for owner / assembled by; reset on reload
        self._protocols = None  # protocol suggestions; reset on reload

    def _columns(self) -> list:
        """The icm.cells columns this database has."""
        columns = list(CELL_COLUMNS)
        if self._db.has_column("cells", "test_length_h"):
            columns += CELL_COLUMNS_024
        if self.has_protocol():
            columns += CELL_COLUMNS_026
        return columns

    def has_protocol(self) -> bool:
        """True once migration 026 added cells.protocol."""
        return self._db.has_column("cells", "protocol")

    def _project_specs(self) -> dict:
        """{project: (density, fe_ppm)}"""
        fe = self.projects_manager.get_project_fe_ppms()
        return {p: (d, fe.get(p, "")) for p, d in self.projects_manager.get_project_densities().items()}

    def _cell_from_row(self, row: dict, specs: dict = None) -> dict:
        cell = {k: to_text(row.get(k)) for k in self._columns()}
        if "test_length_h" in cell:
            cell["test_length_h"] = hours_text(row.get("test_length_h"))
        else:  # before 024: the project's values, no length
            specs = self._project_specs() if specs is None else specs
            cell["density"], cell["fe_ppm"] = specs.get(cell.get("project_id", ""), ("", ""))
            cell["test_length_h"] = ""
        cell.setdefault("protocol", "")
        return cell

    def get_projects_manager(self) -> ProjectsManager:
        """Return the manager handling the configurable project list."""
        return self.projects_manager

    def project_color_for(self, value: str) -> tuple[str, str]:
        """Return ``(background, foreground)`` colors for a project value.

        Known projects get their configured color. Empty or unknown values get
        a fully transparent pill so no colored box is drawn.
        """
        name = (value or "").strip()
        colors = self.projects_manager.get_project_colors()
        if name and name in colors:
            bg = colors[name]
            return bg, ProjectsManager.foreground_for(bg)
        return "transparent", "#1F2A33"

    def clear_project(self, project_name: str) -> int:
        """No-op: the DB FK ``ON DELETE SET NULL`` clears the reference on every
        cell automatically when the project is deleted via the project procs."""
        return 0

    def rename_project(self, old_name: str, new_name: str) -> int:
        """No-op: the DB FK ``ON UPDATE CASCADE`` propagates a project rename to
        every cell automatically when renamed via the project procs."""
        return 0

    # ------------------------------------------------------- Column config
    def get_column_names(self) -> list:
        """Get the list of column names (display names)."""
        return list(self.COLUMNS_MAPPING.keys())

    def get_field_spec(self, column_name: str) -> FieldSpec:
        """Return the :class:`FieldSpec` for ``column_name``."""
        if column_name in self.PEOPLE_COLUMNS:
            return FieldSpec(name=column_name, field_type=FieldType.SUGGEST,
                             choices=self.get_people())
        if column_name == "Protocol":
            return FieldSpec(name=column_name, field_type=FieldType.SUGGEST,
                             choices=self.get_protocols())
        # Project ID is a dropdown populated from the configurable project list.
        if column_name == "Project ID":
            projects = sorted(self.projects_manager.get_projects(), key=str.casefold)
            return FieldSpec(
                name="Project ID",
                field_type=FieldType.CHOICE,
                choices=[""] + projects,
                color_resolver=self.project_color_for,
            )
        return self.FIELD_SPECS.get(
            column_name, FieldSpec(name=column_name, field_type=FieldType.TEXT)
        )

    def get_field_specs(self) -> list[FieldSpec]:
        """Return field specs in column order."""
        return [self.get_field_spec(name) for name in self.get_column_names()]

    def get_column_keys(self) -> list:
        """Get the list of column keys corresponding to columns."""
        return list(self.COLUMNS_MAPPING.values())

    def get_csv_key_for_column(self, column_name: str) -> str:
        """Get the column key for a given column display name."""
        return self.COLUMNS_MAPPING.get(column_name, "")

    def get_column_name_for_key(self, csv_key: str) -> str:
        """Get the column display name for a given column key."""
        for col_name, key in self.COLUMNS_MAPPING.items():
            if key == csv_key:
                return col_name
        return ""

    # Fields that suggest the names already used for either of them.
    PEOPLE_COLUMNS = ("Current owner", "Assembled by")

    def get_people(self) -> list:
        """Names used as owner or assembler in cells and history, most used first.
        Spellings differing only in case count as one (the most used wins)."""
        if self._people is None:
            try:
                rows = self._db.fetch_all(
                    "SELECT LTRIM(RTRIM(v)) AS name, COUNT(*) AS n FROM ("
                    " SELECT current_owner AS v FROM icm.cells"
                    " UNION ALL SELECT assembled_by FROM icm.cells"
                    " UNION ALL SELECT current_owner FROM icm.channel_history"
                    " UNION ALL SELECT assembled_by FROM icm.channel_history) x"
                    " WHERE NULLIF(LTRIM(RTRIM(v)), '') IS NOT NULL"
                    " GROUP BY LTRIM(RTRIM(v)) ORDER BY n DESC, name")
            except DatabaseError:
                return []  # no suggestions this time; typing still works
            seen, people = set(), []
            for r in rows:
                name = to_text(r.get("name"))
                if name.casefold() not in seen:
                    seen.add(name.casefold())
                    people.append(name)
            self._people = people
        return self._people

    def get_protocols(self) -> list:
        """Protocols to suggest, newest first: those on cells and history, then
        experiment plans, then the IC Logbook's last 30. Case duplicates count once."""
        if self._protocols is None:
            sources = []
            if self.has_protocol():
                sources.append(
                    "SELECT protocol FROM (SELECT protocol, id FROM icm.channel_history"
                    " UNION ALL SELECT protocol, id FROM icm.cells) x"
                    " WHERE NULLIF(LTRIM(protocol), '') IS NOT NULL"
                    " GROUP BY protocol ORDER BY MAX(id) DESC")
            sources += [
                "SELECT protocol FROM icm.experiment_plan WHERE NULLIF(LTRIM(protocol), '') IS NOT NULL"
                " GROUP BY protocol ORDER BY MAX(id) DESC",
                "SELECT TOP 30 protocol FROM icm.ic_logbook WHERE NULLIF(LTRIM(protocol), '') IS NOT NULL"
                " GROUP BY protocol ORDER BY MAX(id) DESC",
            ]
            seen, protocols = set(), []
            for sql in sources:
                try:
                    rows = self._db.fetch_all(sql)
                except DatabaseError:
                    continue  # that table isn't there (yet)
                for r in rows:
                    p = to_text(r.get("protocol")).strip()
                    if p.casefold() not in seen:
                        seen.add(p.casefold())
                        protocols.append(p)
            self._protocols = protocols
        return self._protocols

    # ----------------------------------------------------------- Data reads
    def load_all_cells(self) -> list:
        """Load all immersion cells as string-valued dicts."""
        self._people = self._protocols = None  # suggestions may have changed too
        columns = self._columns()
        rows = self._db.fetch_all(f"SELECT {', '.join(columns)} FROM icm.cells ORDER BY id")
        specs = None if "test_length_h" in columns else self._project_specs()
        return [self._cell_from_row(r, specs) for r in rows]

    def get_table_data(self) -> list:
        """Get immersion cells data formatted for table display (list of rows)."""
        cells = self.load_all_cells()
        table_data = []
        for cell in cells:
            row = []
            for csv_key in self.get_column_keys():
                if csv_key == "duration":
                    row.append(self._calculate_duration(cell))
                else:
                    row.append(cell.get(csv_key, ""))
            table_data.append(row)
        return table_data

    def _calculate_duration(self, cell: dict) -> str:
        """Calculate duration as ``now - (start_date + start_hour)``, in hours."""
        start_date_str = (cell.get("start_date") or "").strip()
        start_hour_str = (cell.get("start_hour") or "0").strip()
        if not start_date_str:
            return ""
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            start_hour = int(start_hour_str)
            start_datetime = start_date.replace(hour=start_hour, minute=0, second=0)
            total_seconds = int((datetime.now() - start_datetime).total_seconds())
            if total_seconds < 0:
                return ""
            return f"{total_seconds // 3600}h"
        except (ValueError, AttributeError):
            return ""

    def duration_hours(self, cell: dict) -> str:
        """Whole hours from the cell's start until now, as text ("" if unknown)."""
        return self._calculate_duration(cell).rstrip("h")

    def filename_exists(self, data_filename: str, exclude_id=None) -> bool:
        """Return True if ``data_filename`` is already used by an experiment.

        Calls ``usp_history_filename_exists`` (migration 012), data_filename is a
        unique key. Fails open (returns False) if the check can't run, so a
        missing proc never blocks saving.
        """
        name = (data_filename or "").strip()
        if not name:
            return False
        try:
            row = self._db.fetch_row(
                "EXEC [icm].[usp_history_filename_exists] "
                "@data_filename = ?, @exclude_id = ?",
                (name, exclude_id),
            )
            return bool(row and int(row.get("match_count", 0) or 0) > 0)
        except DatabaseError as e:
            print(f"filename_exists check unavailable (allowing save): {e}")
            return False

    # ------------------------------------------------- Filename generation
    def next_ic_number(self) -> int:
        """Highest ``IC####`` used in any data_filename + 1 (gaps are fine)."""
        try:
            rows = self._db.fetch_all(
                "SELECT data_filename FROM icm.cells WHERE data_filename LIKE 'IC%' "
                "UNION "
                "SELECT data_filename FROM icm.channel_history "
                "WHERE data_filename LIKE 'IC%'"
            )
        except DatabaseError:
            rows = []
        max_n = 0
        for r in rows:
            m = re.match(r"IC(\d+)", to_text(r.get("data_filename")))
            if m:
                max_n = max(max_n, int(m.group(1)))
        return max_n + 1

    def build_data_filename(self, cathode: str, anode: str, channel: str,
                            project_id: str, density: str = None,
                            fe_ppm: str = None) -> str:
        """Assemble the standard data filename.

        ``IC{n}_Cat{cathode}_Ano{anode}_rho{density}_{fe}ppm_Fe_{channel}``,
        density + Fe are the cell's (the project's when not given); the IC
        number auto-increments (4+ digits). Values are trimmed and inserted verbatim.
        """
        if density is None:
            density = self.projects_manager.get_density(project_id)
        if fe_ppm is None:
            fe_ppm = self.projects_manager.get_fe_ppm(project_id)
        return "_".join([
            f"IC{self.next_ic_number():04d}",
            f"Cat{(cathode or '').strip()}",
            f"Ano{(anode or '').strip()}",
            f"rho{(density or '').strip()}",
            f"{(fe_ppm or '').strip()}ppm",
            "Fe",
            (channel or "").strip(),
        ])

    def get_cell_by_channel(self, channel: str) -> dict:
        """Get a specific immersion cell by its channel ID (or {} if missing)."""
        columns = ", ".join(self._columns())
        row = self._db.fetch_row(
            f"SELECT {columns} FROM icm.cells WHERE channel = ?", (channel,)
        )
        return self._cell_from_row(row) if row else {}

    # ---------------------------------------------------------- Data writes
    def _row_to_proc_params(self, row_data: list) -> dict:
        """Map a display-ordered row (list) to stored-proc parameters.

        ``Duration`` is skipped (computed). Empty strings become ``None``
        (NULL); ``start_hour`` is coerced to an int.
        """
        values: dict[str, str] = {}
        idx = 0
        for csv_key in self.get_column_keys():
            if csv_key == "duration":
                idx += 1
                continue
            values[csv_key] = row_data[idx] if idx < len(row_data) else ""
            idx += 1

        params = {k: to_param(values.get(k, "")) for k in self._columns()}
        if "test_length_h" in params:
            params["test_length_h"] = hours_param(params["test_length_h"])
        if params.get("start_hour") is not None:
            try:
                params["start_hour"] = int(params["start_hour"])
            except (ValueError, TypeError):
                params["start_hour"] = None
        return params

    def update_row_by_channel(self, row_data: list) -> None:
        """Update a cell by matching its channel ID (via ``usp_cell_update``)."""
        params = self._row_to_proc_params(row_data)
        if not params.get("channel"):
            raise ValueError("Channel ID cannot be empty")
        self._db.exec_proc("usp_cell_update", params)

    def set_channel_status_cleared(self, channel: str, status: str,
                                   comment: str = None) -> None:
        """Set a channel's cell to ``status`` and clear its experiment fields.

        Used by the calibration coupling (fail -> In repair, pass -> Available):
        only channel/status/comment are sent, so every other field defaults to
        NULL in usp_cell_update and the cell is freed. The comment is kept to
        record why (e.g. a failed calibration).
        """
        if not (channel or "").strip():
            raise ValueError("Channel ID cannot be empty")
        params = {"channel": channel, "status": status}
        if comment is not None:
            params["comments"] = comment
        self._db.exec_proc("usp_cell_update", params)

    def free_channel(self, channel: str) -> None:
        """Free a channel's cell to Available, clearing the experiment fields but
        keeping Added water / Separator, the same fields the editor keeps when
        you free a cell manually. Used when an experiment is deleted."""
        channel = (channel or "").strip()
        if not channel:
            raise ValueError("Channel ID cannot be empty")
        cell = self.get_cell_by_channel(channel)
        # Only channel/status + the kept fields are sent; usp_cell_update NULLs
        # every other column, freeing the cell.
        self._db.exec_proc("usp_cell_update", {
            "channel": channel,
            "status": "Available",
            "added_water_b": to_param(cell.get("added_water_b", "")),
            "separator": to_param(cell.get("separator", "")),
        })

    def add_new_row(self, row_data: list) -> None:
        """Insert a new cell (via ``usp_cell_insert``)."""
        params = self._row_to_proc_params(row_data)
        if not params.get("channel"):
            raise ValueError("Channel ID cannot be empty")
        self._db.exec_proc("usp_cell_insert", params)

    def delete_row_by_channel(self, channel: str) -> None:
        """Delete a cell by its channel ID (via ``usp_cell_delete``)."""
        if not channel:
            raise ValueError("Channel ID cannot be empty")
        self._db.exec_proc("usp_cell_delete", {"channel": channel})
