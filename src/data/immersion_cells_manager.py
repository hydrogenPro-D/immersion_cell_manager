"""Manager for immersion cells data and configuration.

Backed by the ``icm.cells`` table: reads via ``SELECT``, writes via the
``icm.usp_cell_*`` stored procedures. ``Duration`` is computed at runtime and is
not stored.
"""

from datetime import datetime

from src.data.db import get_db, DatabaseError, to_text, to_param
from src.data.projects_manager import ProjectsManager
from src.data.enums import CellStatus
from src.gui.widgets.field_types import FieldSpec, FieldType

# DB columns on icm.cells (in a stable order; ``duration`` is computed, not stored).
CELL_COLUMNS = [
    "channel", "status", "project_id", "current_owner", "assembled_by",
    "start_date", "start_hour", "cathode", "anode", "data_filename",
    "added_water_b", "comments", "separator",
]


class ImmersionCellsManager:
    """Manages immersion cells data and column configuration."""

    # Mapping of display names to column keys.
    COLUMNS_MAPPING = {
        "Channel": "channel",
        "Status": "status",
        "Project ID": "project_id",
        "Current owner": "current_owner",
        "Assembled by": "assembled_by",
        "Start date": "start_date",
        "Start hour": "start_hour",
        "Duration": "duration",
        "Cathode": "cathode",
        "Anode": "anode",
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
        # Project ID is a dropdown populated from the configurable project list.
        if column_name == "Project ID":
            return FieldSpec(
                name="Project ID",
                field_type=FieldType.CHOICE,
                choices=[""] + self.projects_manager.get_projects(),
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

    # ----------------------------------------------------------- Data reads
    def load_all_cells(self) -> list:
        """Load all immersion cells from the database as string-valued dicts."""
        columns = ", ".join(CELL_COLUMNS)
        rows = self._db.fetch_all(f"SELECT {columns} FROM icm.cells ORDER BY id")
        return [{k: to_text(r.get(k)) for k in CELL_COLUMNS} for r in rows]

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

    def get_cell_by_channel(self, channel: str) -> dict:
        """Get a specific immersion cell by its channel ID (or {} if missing)."""
        columns = ", ".join(CELL_COLUMNS)
        row = self._db.fetch_row(
            f"SELECT {columns} FROM icm.cells WHERE channel = ?", (channel,)
        )
        return {k: to_text(row.get(k)) for k in CELL_COLUMNS} if row else {}

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

        params = {k: to_param(values.get(k, "")) for k in CELL_COLUMNS}
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
