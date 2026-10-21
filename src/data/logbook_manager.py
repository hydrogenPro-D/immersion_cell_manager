"""Manager for the IC Logbook tab (historical experiments).

Backed by the database: reads ``icm.ic_logbook`` / ``icm.ic_logbook_scoreboard``
via SELECT, writes scoreboard changes via the ``icm.usp_ic_logbook_scoreboard_*``
procs. The key is an auto-increment ``id``; ``ic_id`` is a plain, non-unique text
column. The GUI is unaware of the source.

Projects (= sub-tabs) and their columns come from ``icm.ic_logbook_project`` /
``_project_column`` (migration 020); custom-column values from
``icm.ic_logbook_value``. Without 020 the old fixed columns are used.
"""

import json
import uuid
from datetime import date, datetime

from src.data.db import get_db, DatabaseError, to_text, to_param, db_message as _db_message

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

# Built-in ic_logbook columns with a non-text type (the rest are text).
BUILTIN_TYPES = {
    "test_length_h": "number", "experiment_finished_on": "date",
    "synthesis_time_h": "number", "synthesis_temperature_c": "number",
}
BUILTIN_FIELDS = [f for f, _ in STANDARD_COLUMNS + EXTRA_COLUMNS]
# Every project keeps these: IC_ID identifies a row, hours feed the Summary.
LOCKED_FIELDS = ("ic_id", "test_length_h")
# "Summary" is the overview tab; a project with that name would replace it.
RESERVED_PROJECT_NAMES = ("summary",)
PROJECT_NAME_MAX = 64  # icm.ic_logbook.category is NVARCHAR(64)

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
        self._has_archive = False  # set by _fetch_projects (migration 021)
        self._has_rename = None    # checked once, on first can_rename()
        self.reload()

    # ------------------------------------------------------------------ IO
    def reload(self) -> None:
        """(Re)load the logbook + scoreboard from the database."""
        self._load_rows()
        self._load_scoreboard()

    def _load_rows(self) -> None:
        cols = ", ".join(_LOGBOOK_COLUMNS)
        try:
            recs = self._db.fetch_all(
                f"SELECT {cols} FROM icm.ic_logbook ORDER BY id")
        except DatabaseError:
            recs = []  # tables not created yet
        self._rows = [self._experiment_row(r) for r in recs]
        self._load_projects()

    def _load_scoreboard(self) -> None:
        try:
            sb = self._db.fetch_all(
                "SELECT id, snapshot_date, days_since_intro, total_testing_time_h,"
                " number_of_ics FROM icm.ic_logbook_scoreboard ORDER BY id")
        except DatabaseError:
            sb = []
        self._scoreboard = [self._scoreboard_row(r) for r in sb]

    def _load_projects(self) -> None:
        """Projects, their columns and the custom-column values (migration 020).
        ``self._projects`` stays None when 020 hasn't been run."""
        self._archived = set()
        try:
            projects = self._fetch_projects()
            columns = self._db.fetch_all(
                "SELECT project_id, field_key, label, data_type"
                " FROM icm.ic_logbook_project_column ORDER BY project_id, position")
            values = self._db.fetch_all(
                "SELECT logbook_id, field_key, value FROM icm.ic_logbook_value")
        except DatabaseError:
            self._projects = None
            return
        cols_by_project = {}
        for c in columns:
            cols_by_project.setdefault(c["project_id"], []).append(
                (c["field_key"], c["label"], c["data_type"]))
        self._projects = {p["name"]: cols_by_project.get(p["id"], []) for p in projects}
        self._archived = {p["name"] for p in projects if p.get("is_archived")}
        by_id = {r["id"]: r for r in self._rows}
        for v in values:
            row = by_id.get(v["logbook_id"])
            if row is not None:
                row[v["field_key"]] = to_text(v["value"])

    def _fetch_projects(self) -> list:
        # is_archived arrives with migration 021; without it nothing is archived.
        try:
            rows = self._db.fetch_all(
                "SELECT id, name, is_archived FROM icm.ic_logbook_project"
                " ORDER BY sort_order, id")
            self._has_archive = True
            return rows
        except DatabaseError:
            self._has_archive = False
            return self._db.fetch_all(
                "SELECT id, name FROM icm.ic_logbook_project ORDER BY sort_order, id")

    def can_archive(self) -> bool:
        """True once migration 021 is in (projects can be archived)."""
        return self._projects is not None and self._has_archive

    def has_projects(self) -> bool:
        """True once migration 020 is in (projects can be created)."""
        return self._projects is not None

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
    def get_categories(self, include_archived: bool = False) -> list:
        """Project categories (one sub-tab each), in workbook order. Archived
        projects are left out unless ``include_archived``."""
        if self._projects is not None:
            names = [n for n in self._projects
                     if include_archived or n not in self._archived]
            # A category used in the data but missing from the table still shows.
            names += [c for c in dict.fromkeys(r.get("category") or "" for r in self._rows)
                      if c and c not in self._projects]
            return names
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

    def get_experiment(self, exp_id):
        """One experiment row by id, or None (e.g. deleted by another user)."""
        return next((r for r in self._rows if exp_id is not None and r.get("id") == exp_id), None)

    def get_experiments(self, category: str) -> list:
        """All experiment rows (dicts) for a category."""
        return [r for r in self._rows if (r.get("category") or "") == category]

    def get_recent_values(self, field: str, category: str = None, limit: int = 30) -> list:
        """Distinct non-empty values of ``field``, most recently added first
        (offered as dropdown suggestions); only ``category``'s rows if given."""
        seen, out = set(), []
        for r in reversed(self._rows):  # rows are loaded in id order
            if category and r.get("category") != category:
                continue
            v = (r.get(field) or "").strip()
            if v and v not in seen:
                seen.add(v)
                out.append(v)
                if len(out) >= limit:
                    break
        return out

    def get_columns(self, category: str):
        """``[(field, header), ...]`` to show: the project's own columns, or (no
        020 / unknown project) the standard set plus any extra column that has
        data in this category."""
        if self._projects is not None and self._projects.get(category):
            return [(f, label) for f, label, _ in self._projects[category]]
        cols = list(STANDARD_COLUMNS)
        rows = self.get_experiments(category)
        for field, header in EXTRA_COLUMNS:
            if any((r.get(field) or "").strip() for r in rows):
                cols.append((field, header))
        return cols

    def get_archived_categories(self) -> list:
        return [n for n in (self._projects or {}) if n in self._archived]

    def get_project_names(self, archived: bool) -> list:
        """Real projects only (not categories that exist just in the data)."""
        return [n for n in (self._projects or {}) if (n in self._archived) == archived]

    def validate_project_name(self, name: str, taken: list = None) -> str:
        """"" if ``name`` can be used, else why not. ``taken``: the names it may
        not clash with (default: every project and category, archived too)."""
        name = name.strip()
        if not name:
            return "Please enter a project name."
        if len(name) > PROJECT_NAME_MAX:
            return f"A project name can be at most {PROJECT_NAME_MAX} characters."
        if name.lower() in RESERVED_PROJECT_NAMES:
            return f'"{name}" is reserved for the overview tab.'
        if taken is None:
            taken = self.get_categories(include_archived=True)
        if name.lower() in (t.strip().lower() for t in taken):
            return f"A project called '{name}' already exists."
        return ""

    def can_rename(self) -> bool:
        """True once migration 022 is in (projects can be renamed)."""
        if self._has_rename is None:
            try:
                row = self._db.fetch_row(
                    "SELECT OBJECT_ID('icm.usp_ic_logbook_project_rename') AS o")
                self._has_rename = bool(row and row["o"] is not None)
            except DatabaseError:
                return False
        return self._has_rename

    def apply_project_changes(self, renames: dict, archived: dict) -> str:
        """Renames {old: new} first, then archive / restore {name: archived}
        (by the new names); one reload at the end. "" on success, else the error."""
        try:
            for old, new in renames.items():
                self._db.exec_proc("usp_ic_logbook_project_rename",
                                   {"old_name": old, "new_name": new})
            for name, is_archived in archived.items():
                self._db.exec_proc("usp_ic_logbook_project_set_archived",
                                   {"name": name, "is_archived": 1 if is_archived else 0})
        except DatabaseError as e:
            return _db_message(e)
        finally:
            self._load_rows()  # some changes may be in even after an error
        return ""

    def get_column_types(self, category: str) -> dict:
        """``{field: "text" | "number" | "date"}`` for the project's columns."""
        if self._projects is not None and self._projects.get(category):
            return {f: t for f, _, t in self._projects[category]}
        return {f: BUILTIN_TYPES.get(f, "text") for f, _ in self.get_columns(category)}

    def get_summary(self) -> dict:
        """Live totals: per-category count + testing hours (active and archived
        projects apart), and grand totals over every experiment.

        Categories are ordered to match the Excel Summary sheet; any not listed
        there are appended in workbook order.
        """
        cats = self.get_categories(include_archived=True)
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
        archived = [c for c in per_category if c["category"] in self._archived]
        return {
            "per_category": [c for c in per_category if c["category"] not in self._archived],
            "per_category_archived": archived,
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
            new_id = self._db.exec_proc("usp_ic_logbook_insert", params, returns_id=True)
            self._write_custom_values(new_id, values)
            return True
        except DatabaseError:
            return False
        finally:
            self._load_rows()  # after a failure too: show what is stored

    def update_experiment(self, exp_id, values: dict) -> bool:
        """Update an existing experiment by its id. Fields not in ``values``
        (e.g. columns its project doesn't show) keep their stored value."""
        current = next((r for r in self._rows if r.get("id") == exp_id), {})
        merged = {**current, **values}
        params = self._experiment_params(merged)
        params["id"] = int(exp_id)
        try:
            self._db.exec_proc("usp_ic_logbook_update", params)
            self._write_custom_values(exp_id, values)
            return True
        except (DatabaseError, ValueError, TypeError):
            return False
        finally:
            self._load_rows()

    def move_experiment(self, exp_id, category: str, values: dict = None) -> bool:
        """Move an experiment to another project (optionally saving edits too).
        Values for columns the new project lacks are kept, just not shown."""
        return self.update_experiment(exp_id, {**(values or {}), "category": category})

    def _write_custom_values(self, exp_id, values: dict) -> None:
        if self._projects is None or exp_id is None:
            return
        for key, value in values.items():
            if key not in BUILTIN_FIELDS and key not in ("id", "category"):
                self._db.exec_proc("usp_ic_logbook_value_set", {
                    "logbook_id": int(exp_id), "field_key": key,
                    "value": to_param(str(value or ""))})

    # -------------------------------------------------------- Project writes
    @staticmethod
    def new_custom_key() -> str:
        """Storage key for a user-added column (labels can repeat across projects)."""
        return "x_" + uuid.uuid4().hex[:10]

    def add_project(self, name: str, columns: list) -> str:
        """Create a project. ``columns``: [{"field_key", "label", "data_type"}]
        in display order. Returns "" on success, else the error message."""
        try:
            self._db.exec_proc("usp_ic_logbook_project_create", {
                "name": name.strip(),
                "columns": json.dumps(columns, ensure_ascii=False),
            }, returns_id=True)
        except DatabaseError as e:
            return _db_message(e)
        self._load_rows()
        return ""

    def delete_experiment(self, exp_id) -> bool:
        """Delete an experiment by its id."""
        try:
            self._db.exec_proc("usp_ic_logbook_delete", {"id": int(exp_id)})
            return True
        except (DatabaseError, ValueError, TypeError):
            return False
        finally:
            self._load_rows()

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
            return True
        except DatabaseError:
            return False
        finally:
            self._load_scoreboard()

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
            return True
        except DatabaseError:
            return False
        finally:
            self._load_scoreboard()

    def delete_scoreboard(self, index: int) -> bool:
        """Remove a snapshot by row index."""
        if not (0 <= index < len(self._scoreboard)):
            return False
        sid = self._scoreboard[index].get("id")
        try:
            self._db.exec_proc("usp_ic_logbook_scoreboard_delete", {"id": int(sid)})
            return True
        except DatabaseError:
            return False
        finally:
            self._load_scoreboard()

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
