"""Seed the database with initial data after the migrations have run.

What this loads:
  * ``icm.cells``           -> from ``immersion_cells_template.csv`` (the blank
                              channel list, all "Available").
  * ``icm.projects``        -> nothing (start empty by design).
  * ``icm.channel_history`` -> nothing (start empty by design).

It is **insert-missing only**: a channel that already exists is left untouched,
so re-running this is safe and never overwrites data the app has since written.

Connection: the loader **prompts** on the command line -- pick the target
database, then type the server, username, and password (hidden).

Use a privileged login (the one you run the migrations with) -- the app role
``ic_manager_role`` may not have INSERT rights.

Usage:
    python -m src.data.sql.load_initial_data            # load the template
    python -m src.data.sql.load_initial_data --dry-run  # show what would change
    python -m src.data.sql.load_initial_data --csv path/to/other.csv
"""

import argparse
import csv
import getpass
import sys
from pathlib import Path

# Databases this loader offers / is willing to touch (mirrors the migrations'
# guard). Listed test-first so the default prompt choice is the safer one.
DATABASES = ["dataloggingTest", "dataloggingDev"]
ALLOWED_DATABASES = set(DATABASES)

DEFAULT_DRIVER = "ODBC Driver 18 for SQL Server"

# Columns in icm.cells we populate (duration is computed at runtime, not stored).
CELL_COLUMNS = [
    "channel", "status", "project_id", "current_owner", "assembled_by",
    "start_date", "start_hour", "cathode", "anode", "data_filename",
    "added_water_b", "comments", "separator",
]

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "csv" / "immersion_cells_template.csv"


def read_cells(csv_path: Path) -> list[dict]:
    """Read the template CSV into row dicts keyed by DB column.

    Empty strings become ``None`` (SQL NULL); ``start_hour`` is coerced to int.
    """
    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            channel = (raw.get("channel") or "").strip()
            if not channel:
                continue
            row = {col: ((raw.get(col) or "").strip() or None) for col in CELL_COLUMNS}
            if row["start_hour"] is not None:
                try:
                    row["start_hour"] = int(row["start_hour"])
                except ValueError:
                    row["start_hour"] = None
            rows.append(row)
    return rows


def prompt_for_connection() -> str:
    """Ask the user for the database, server, username, and password."""
    print("Select the target database:")
    for i, name in enumerate(DATABASES, 1):
        print(f"  {i}) {name}")
    raw = input(f"Choice [1-{len(DATABASES)}, default 1]: ").strip() or "1"
    try:
        idx = int(raw)
    except ValueError:
        idx = 0
    if not 1 <= idx <= len(DATABASES):
        raise SystemExit("Invalid database choice.")
    database = DATABASES[idx - 1]

    server = input("Server: ").strip()
    if not server:
        raise SystemExit("Server is required.")

    username = input("Username: ").strip()
    if not username:
        raise SystemExit("Username is required.")

    password = getpass.getpass("Password: ")
    if not password:
        raise SystemExit("Password is required.")

    return (
        f"DRIVER={{{DEFAULT_DRIVER}}};SERVER={server};DATABASE={database};"
        f"UID={username};PWD={password};Encrypt=yes;TrustServerCertificate=no;"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Seed icm.cells from a template CSV.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV,
                        help=f"CSV to load (default: {DEFAULT_CSV.name}).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be inserted without writing.")
    parser.add_argument("--allow-any-db", action="store_true",
                        help="Skip the dataloggingDev/dataloggingTest name guard.")
    args = parser.parse_args(argv)

    if not args.csv.exists():
        raise SystemExit(f"CSV not found: {args.csv}")

    rows = read_cells(args.csv)
    print(f"Read {len(rows)} cell row(s) from {args.csv.name}.")

    import pyodbc  # imported lazily so CSV parsing is testable without the driver

    connection_string = prompt_for_connection()
    with pyodbc.connect(connection_string, autocommit=False) as conn:
        cur = conn.cursor()

        db_name = cur.execute("SELECT DB_NAME()").fetchval()
        if not args.allow_any_db and db_name not in ALLOWED_DATABASES:
            raise SystemExit(
                f"Refusing to run against '{db_name}'. Expected one of "
                f"{sorted(ALLOWED_DATABASES)} (use --allow-any-db to override)."
            )
        print(f"Connected to database '{db_name}'.")

        if cur.execute("SELECT OBJECT_ID(N'[icm].[cells]', N'U')").fetchval() is None:
            raise SystemExit("[icm].[cells] does not exist. Run migrations 001-006 first.")

        # Don't reinsert channels that already exist.
        existing = {r[0] for r in cur.execute("SELECT channel FROM icm.cells")}
        to_insert = [r for r in rows if r["channel"] not in existing]
        skipped = len(rows) - len(to_insert)

        # A non-null project_id must already exist in icm.projects (FK), but we
        # are loading projects empty -- catch this early with a clear message.
        referenced = {r["project_id"] for r in to_insert if r["project_id"]}
        if referenced:
            known = {r[0] for r in cur.execute("SELECT project_id FROM icm.projects")}
            missing = sorted(referenced - known)
            if missing:
                raise SystemExit(
                    "These project_id values are not in icm.projects and would "
                    f"violate the FK: {missing}. Load those projects first, or "
                    "clear the column in the CSV."
                )

        if not to_insert:
            print(f"Nothing to insert ({skipped} channel(s) already present).")
            return 0

        col_list = ", ".join(f"[{c}]" for c in CELL_COLUMNS)
        placeholders = ", ".join(["?"] * len(CELL_COLUMNS))
        insert_sql = f"INSERT INTO icm.cells ({col_list}) VALUES ({placeholders})"
        params = [[r[c] for c in CELL_COLUMNS] for r in to_insert]

        if args.dry_run:
            print(f"[dry-run] Would insert {len(to_insert)} channel(s); "
                  f"{skipped} already present. No changes made.")
            return 0

        cur.fast_executemany = True
        cur.executemany(insert_sql, params)
        conn.commit()
        print(f"Inserted {len(to_insert)} channel(s); {skipped} already present.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
