"""Manager for the IC Logbook tab (historical experiments).

Backed by the database: reads ``icm.ic_logbook`` / ``icm.ic_logbook_scoreboard``
via SELECT, writes scoreboard changes via the ``icm.usp_ic_logbook_scoreboard_*``
procs. The key is an auto-increment ``id``; ``ic_id`` is a plain, non-unique text
column. The GUI is unaware of the source.
"""

from datetime import date, datetime

from src.data.db import get_db, DatabaseError, to_text, to_param

# The date the IC_ID system was introduced (auto-computes a new snapshot's
# "days since intro"; kept in sync with the Excel Summary sheet).
ID_INTRO_DATE = date(2024, 9, 4)

# Sub-tab order (the workbook's sheet order). Categories present in the data but
# not listed here are appended after, in first-seen order.
CATEGORY_ORDER = [
    "Gen2-Gen2", "Gen3-Gen3", "Gen2-Gen3Ano", "Gen3Cat-Gen2", "Gen4Cat-Gen2",
    "Accelerated", "H2-FOAM", "LC-H2", "H2-Electrode", "H2-SAF", "H2-Giga",
    "MLF", "Sulfidized", "Substrate tests", "External | Meshes",
    "Production R&D", "Long term testing", "Iron tests", "Other",
]

# Order for the Summary per-category table (Excel "1. Summary" matrix order).
SUMMARY_CATEGORY_ORDER = [
    "Gen3-Gen3", "Gen2-Gen3Ano", "Gen3Cat-Gen2", "Gen2-Gen2", "Accelerated",
    "H2-FOAM", "LC-H2", "H2-Electrode", "MLF", "Sulfidized", "Substrate tests",
    "H2-SAF", "Production R&D", "Long term testing", "H2-Giga", "Other",
]

# (field, header) for the columns every category shows.
STANDARD_COLUMNS = [
    ("ic_id", "IC_ID"),
    ("owner", "Owner"),
    ("assembled_by", "Assembled by"),
    ("disassembled_by", "Disassembled by"),
    ("test_length_h", "Test length [h]"),
    ("protocol", "Protocol"),
    ("format", "Format"),
    ("experiment_finished_on", "Experiment finished on"),
    ("notes", "Notes"),
    ("archived_in", "Archived in"),
    ("plot", "Plot"),
]

# Extra columns shown only for a category that actually uses them (e.g. Sulfidized).
EXTRA_COLUMNS = [
    ("synthesis_recipe", "Synthesis recipe"),
    ("synthesis_time_h", "Synthesis time (h)"),
    ("synthesis_temperature_c", "Synthesis temp (°C)"),
    ("coating_test_on", "Coating test on"),
]

# ic_logbook columns, in SELECT order.
_LOGBOOK_COLUMNS = [
    "id", "category", "ic_id", "owner", "assembled_by", "disassembled_by",
    "test_length_h", "protocol", "format", "experiment_finished_on", "notes",
    "archived_in", "plot", "synthesis_recipe", "synthesis_time_h",
    "synthesis_temperature_c", "coating_test_on",
]


class LogbookManager:
    """Reads the historical experiment logbook + scoreboard from the DB."""

    def __init__(self, db=None):
        self._db = db or get_db()
        self._rows = []
        self._scoreboard = []
        self.reload()

    # ------------------------------------------------------------------ IO
    def reload(self) -> None:
        """(Re)load the logbook + scoreboard from the database."""
        cols = ", ".join(_LOGBOOK_COLUMNS)
        try:
            recs = self._db.fetch_all(
                f"SELECT {cols} FROM icm.ic_logbook ORDER BY id")
        except DatabaseError:
            recs = []  # tables not created yet
        self._rows = [self._experiment_row(r) for r in recs]

        try:
            sb = self._db.fetch_all(
                "SELECT id, snapshot_date, days_since_intro, total_testing_time_h,"
                " number_of_ics FROM icm.ic_logbook_scoreboard ORDER BY id")
        except DatabaseError:
            sb = []
        self._scoreboard = [self._scoreboard_row(r) for r in sb]

    def _experiment_row(self, r: dict) -> dict:
        return {
            "id": r.get("id"),
            "category": to_text(r.get("category")),
            "ic_id": to_text(r.get("ic_id")),
            "owner": to_text(r.get("owner")),
            "assembled_by": to_text(r.get("assembled_by")),
            "disassembled_by": to_text(r.get("disassembled_by")),
            "test_length_h": self._num_text(r.get("test_length_h")),
            "protocol": to_text(r.get("protocol")),
            "format": to_text(r.get("format")),
            "experiment_finished_on": to_text(r.get("experiment_finished_on")),
            "notes": to_text(r.get("notes")),
            "archived_in": to_text(r.get("archived_in")),
            "plot": to_text(r.get("plot")),
            "synthesis_recipe": to_text(r.get("synthesis_recipe")),
            "synthesis_time_h": self._num_text(r.get("synthesis_time_h")),
            "synthesis_temperature_c": self._num_text(r.get("synthesis_temperature_c")),
            "coating_test_on": to_text(r.get("coating_test_on")),
        }

    def _scoreboard_row(self, r: dict) -> dict:
        # Keys match what the GUI expects; `id` is kept for edit/delete by id.
        return {
            "id": r.get("id"),
            "date": to_text(r.get("snapshot_date")),
            "days_since_id_intro": self._num_text(r.get("days_since_intro")),
            "total_testing_time_h": self._num_text(r.get("total_testing_time_h")),
            "number_of_ics": self._num_text(r.get("number_of_ics")),
        }

    # ----------------------------------------------------------- Public API
    def get_categories(self) -> list:
        """Project categories (one sub-tab each), in workbook order."""
        present = []
        seen = set()
        for r in self._rows:
            c = r.get("category") or ""
            if c and c not in seen:
                seen.add(c)
                present.append(c)
        ordered = [c for c in CATEGORY_ORDER if c in seen]
        ordered += [c for c in present if c not in ordered]
        return ordered

    def get_experiments(self, category: str) -> list:
        """All experiment rows (dicts) for a category."""
        return [r for r in self._rows if (r.get("category") or "") == category]

    def get_columns(self, category: str):
        """``[(field, header), ...]`` to show: the standard set plus any extra
        column that has data in this category."""
        cols = list(STANDARD_COLUMNS)
        rows = self.get_experiments(category)
        for field, header in EXTRA_COLUMNS:
            if any((r.get(field) or "").strip() for r in rows):
                cols.append((field, header))
        return cols

    def get_summary(self) -> dict:
        """Live totals: per-category count + testing hours, and grand totals.

        Categories are ordered to match the Excel Summary sheet; any not listed
        there are appended in workbook order.
        """
        cats = self.get_categories()
        ordered = [c for c in SUMMARY_CATEGORY_ORDER if c in cats]
        ordered += [c for c in cats if c not in ordered]

        per_category = []
        total_hours = 0.0
        total_count = 0
        for c in ordered:
            rows = self.get_experiments(c)
            hours = sum(self._num(r.get("test_length_h")) for r in rows)
            per_category.append({"category": c, "count": len(rows), "hours": hours})
            total_hours += hours
            total_count += len(rows)
        return {
            "per_category": per_category,
            "total_hours": total_hours,
            "total_count": total_count,
        }

    def get_scoreboard(self) -> list:
        """The manual historical snapshots."""
        return list(self._scoreboard)

    # ----------------------------------------------------- Experiment writes
    def add_experiment(self, category: str, values: dict) -> bool:
        """Insert a new experiment into ``category``."""
        params = self._experiment_params({**values, "category": category})
        try:
            self._db.exec_proc("usp_ic_logbook_insert", params, returns_id=True)
            self.reload()
            return True
        except DatabaseError:
            return False

    def update_experiment(self, exp_id, values: dict) -> bool:
        """Update an existing experiment by its id."""
        params = self._experiment_params(values)
        params["id"] = int(exp_id)
        try:
            self._db.exec_proc("usp_ic_logbook_update", params)
            self.reload()
            return True
        except (DatabaseError, ValueError, TypeError):
            return False

    def delete_experiment(self, exp_id) -> bool:
        """Delete an experiment by its id."""
        try:
            self._db.exec_proc("usp_ic_logbook_delete", {"id": int(exp_id)})
            self.reload()
            return True
        except (DatabaseError, ValueError, TypeError):
            return False

    def _experiment_params(self, v: dict) -> dict:
        return {
            "category": to_param(v.get("category")),
            "ic_id": to_param(v.get("ic_id")),
            "owner": to_param(v.get("owner")),
            "assembled_by": to_param(v.get("assembled_by")),
            "disassembled_by": to_param(v.get("disassembled_by")),
            "test_length_h": self._as_float(v.get("test_length_h", "")),
            "protocol": to_param(v.get("protocol")),
            "format": to_param(v.get("format")),
            "experiment_finished_on": self._as_date(v.get("experiment_finished_on", "")),
            "notes": to_param(v.get("notes")),
            "archived_in": to_param(v.get("archived_in")),
            "plot": to_param(v.get("plot")),
            "synthesis_recipe": to_param(v.get("synthesis_recipe")),
            "synthesis_time_h": self._as_float(v.get("synthesis_time_h", "")),
            "synthesis_temperature_c": self._as_float(v.get("synthesis_temperature_c", "")),
            "coating_test_on": to_param(v.get("coating_test_on")),
        }

    # ------------------------------------------------------ Scoreboard writes
    def update_scoreboard(self, index: int, total_testing_time_h, number_of_ics) -> bool:
        """Update the two manual values of an existing snapshot (by row index)."""
        if not (0 <= index < len(self._scoreboard)):
            return False
        sid = self._scoreboard[index].get("id")
        try:
            self._db.exec_proc("usp_ic_logbook_scoreboard_update", {
                "id": int(sid),
                "total_testing_time_h": self._as_float(total_testing_time_h),
                "number_of_ics": self._as_int(number_of_ics),
            })
            self.reload()
            return True
        except DatabaseError:
            return False

    def add_scoreboard(self, total_testing_time_h, number_of_ics) -> bool:
        """Append a snapshot dated today (days-since-intro auto-computed)."""
        today = date.today()
        try:
            self._db.exec_proc("usp_ic_logbook_scoreboard_insert", {
                "snapshot_date": today.isoformat(),
                "days_since_intro": (today - ID_INTRO_DATE).days,
                "total_testing_time_h": self._as_float(total_testing_time_h),
                "number_of_ics": self._as_int(number_of_ics),
            }, returns_id=True)
            self.reload()
            return True
        except DatabaseError:
            return False

    def delete_scoreboard(self, index: int) -> bool:
        """Remove a snapshot by row index."""
        if not (0 <= index < len(self._scoreboard)):
            return False
        sid = self._scoreboard[index].get("id")
        try:
            self._db.exec_proc("usp_ic_logbook_scoreboard_delete", {"id": int(sid)})
            self.reload()
            return True
        except DatabaseError:
            return False

    # -------------------------------------------------------------- Helpers
    @staticmethod
    def _num(value) -> float:
        try:
            return float(str(value).replace(",", ".").strip())
        except (ValueError, AttributeError):
            return 0.0

    @staticmethod
    def _num_text(value) -> str:
        """Display a DB numeric: drop the trailing .0 on whole numbers."""
        if value is None:
            return ""
        if isinstance(value, float):
            return str(int(value)) if value.is_integer() else str(value)
        return to_text(value)

    @staticmethod
    def _as_float(value):
        s = str(value).replace(",", ".").strip()
        return to_param(s)  # SQL casts the string to FLOAT; "" -> NULL

    @staticmethod
    def _as_int(value):
        s = str(value).strip()
        return to_param(s)  # SQL casts to INT; "" -> NULL

    @staticmethod
    def _as_date(value):
        s = str(value).strip()[:10]
        if not s:
            return None
        try:
            datetime.strptime(s, "%Y-%m-%d")
            return s  # ISO string; SQL casts to DATE
        except ValueError:
            return None
