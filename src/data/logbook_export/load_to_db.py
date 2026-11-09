"""One-time loader: import the IC Logbook CSVs into the database.

Azure SQL can't BULK INSERT local files, so this loads client-side via the app's
DB layer, through the ``usp_ic_logbook_*`` procs (migrations 017-022).

Run extract_logbook.py first, then from the repo root:
  ``python src/data/logbook_export/load_to_db.py``         (Test, config/db_config.json)
  ``python src/data/logbook_export/load_to_db.py --prod``  (prod, config/db_config.prod.json)
It also creates the project tabs (with their columns) that don't exist yet.
It refuses to run if ic_logbook already has rows (pass ``--force`` to load anyway).
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

# Allow running this file directly: put the repo root on sys.path so `src` imports.
_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

from src.data.db import Database, get_db, DatabaseError  # noqa: E402
from src.data.logbook_manager import (  # noqa: E402
    STANDARD_COLUMNS, EXTRA_COLUMNS, BUILTIN_TYPES)

_DIR = Path(__file__).resolve().parent
_LOGBOOK_CSV = _DIR / "ic_logbook.csv"
_SCOREBOARD_CSV = _DIR / "summary_scoreboard.csv"
_PROD_CONFIG = _ROOT / "config" / "db_config.prod.json"
_ALLOWED_DB = ("dataloggingDev", "dataloggingTest")

_nulled = []  # (row_ident, column, raw) for values that couldn't be typed


def to_text(s):
    s = (s or "").strip()
    return s or None


def to_float(s, *, ident="", col=""):
    s = (s or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        _nulled.append((ident, col, s))
        return None


def to_hours(s, *, ident=""):
    """test_length: number, or h:mm:ss duration -> decimal hours, else NULL."""
    raw = (s or "").strip()
    t = raw.replace(",", ".")
    if not t:
        return None
    if ":" in t:
        p = t.split(":")
        try:
            h = int(p[0]); m = int(p[1]) if len(p) > 1 else 0; sec = int(p[2]) if len(p) > 2 else 0
            return round(h + m / 60 + sec / 3600, 4)
        except ValueError:
            _nulled.append((ident, "test_length_h", raw))
            return None
    try:
        return float(t)
    except ValueError:
        _nulled.append((ident, "test_length_h", raw))
        return None


def to_int(s, *, ident="", col=""):
    f = to_float(s, ident=ident, col=col)
    return int(round(f)) if f is not None else None


def to_date(s):
    s = (s or "").strip()[:10]
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def create_projects(db, rows):
    """Create each category's project tab that doesn't exist yet, in workbook order.
    Extra (synthesis) columns only where that category has data in them."""
    existing = {r["name"] for r in db.fetch_all("SELECT name FROM icm.ic_logbook_project")}
    order, extras = [], {}
    for r in rows:
        cat = (r.get("category") or "").strip()
        if not cat:
            continue
        if cat not in extras:
            order.append(cat)
            extras[cat] = set()
        extras[cat].update(f for f, _ in EXTRA_COLUMNS if (r.get(f) or "").strip())

    created = 0
    for cat in order:
        if cat in existing:
            continue
        cols = STANDARD_COLUMNS + [c for c in EXTRA_COLUMNS if c[0] in extras[cat]]
        columns = [{"field_key": f, "label": label, "data_type": BUILTIN_TYPES.get(f, "text")}
                   for f, label in cols]
        try:
            db.exec_proc("usp_ic_logbook_project_create", {
                "name": cat, "columns": json.dumps(columns, ensure_ascii=False),
            }, returns_id=True)
            created += 1
        except DatabaseError as e:
            print(f"  project create failed for {cat}: {e}")
    return created


def main():
    force = "--force" in sys.argv
    prod = "--prod" in sys.argv
    db = Database(_PROD_CONFIG) if prod else get_db()

    row = db.fetch_row("SELECT DB_NAME() AS db")
    dbname = (row or {}).get("db")
    if dbname not in _ALLOWED_DB or (prod and dbname != "dataloggingDev"):
        print(f"Refusing to run: connected to {dbname!r}.")
        return
    print(f"Connected to {dbname}.")

    existing = db.fetch_row("SELECT COUNT(*) AS n FROM icm.ic_logbook")
    n_existing = int((existing or {}).get("n") or 0)
    if n_existing and not force:
        print(f"icm.ic_logbook already has {n_existing} rows. Use --force to load anyway.")
        return

    with open(_LOGBOOK_CSV, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    answer = input(f"Load {len(rows)} experiments into {dbname}? [y/N] ").strip().lower()
    if answer != "y":
        print("Cancelled.")
        return

    n_projects = create_projects(db, rows)

    # Experiments.
    inserted = 0
    for r in rows:
        ident = r.get("ic_id") or f"({r.get('category')})"
        params = {
            "category": to_text(r.get("category")),
            "ic_id": to_text(r.get("ic_id")),
            "owner": to_text(r.get("owner")),
            "assembled_by": to_text(r.get("assembled_by")),
            "disassembled_by": to_text(r.get("disassembled_by")),
            "test_length_h": to_hours(r.get("test_length_h"), ident=ident),
            "protocol": to_text(r.get("protocol")),
            "format": to_text(r.get("format")),
            "experiment_finished_on": to_date(r.get("experiment_finished_on")),
            "notes": to_text(r.get("notes")),
            "archived_in": to_text(r.get("archived_in")),
            "plot": to_text(r.get("plot")),
            "synthesis_recipe": to_text(r.get("synthesis_recipe")),
            "synthesis_time_h": to_float(r.get("synthesis_time_h"),
                                         ident=ident, col="synthesis_time_h"),
            "synthesis_temperature_c": to_float(r.get("synthesis_temperature_c"),
                                                ident=ident, col="synthesis_temperature_c"),
            "coating_test_on": to_text(r.get("coating_test_on")),
        }
        try:
            db.exec_proc("usp_ic_logbook_insert", params, returns_id=True)
            inserted += 1
        except DatabaseError as e:
            print(f"  insert failed for {ident}: {e}")

    # Scoreboard snapshots.
    sb_inserted = 0
    with open(_SCOREBOARD_CSV, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            params = {
                "snapshot_date": to_date(r.get("date")),
                "days_since_intro": to_int(r.get("days_since_id_intro"),
                                           ident="scoreboard", col="days_since_id_intro"),
                "total_testing_time_h": to_float(r.get("total_testing_time_h"),
                                                 ident="scoreboard", col="total_testing_time_h"),
                "number_of_ics": to_int(r.get("number_of_ics"),
                                        ident="scoreboard", col="number_of_ics"),
            }
            try:
                db.exec_proc("usp_ic_logbook_scoreboard_insert", params, returns_id=True)
                sb_inserted += 1
            except DatabaseError as e:
                print(f"  scoreboard insert failed: {e}")

    print(f"\nCreated {n_projects} projects, inserted {inserted} experiments and "
          f"{sb_inserted} scoreboard snapshots.")
    if _nulled:
        print(f"\n{len(_nulled)} values could not be typed and were stored as NULL:")
        for ident, col, raw in _nulled:
            print(f"  {col:<24} {raw!r:<28} ({ident})")


if __name__ == "__main__":
    main()
