# SQL migrations

Manual, ordered, idempotent migrations for the Immersion Cell Manager database.
Conventions are defined in [`../integration/MIGRATION_PLAYBOOK.md`](../integration/MIGRATION_PLAYBOOK.md).

- **Platform:** Azure SQL Database
- **Schema:** `icm` (owns all tables + the `schema_migrations` ledger)
- **Allowed databases (wrong-DB guard):** `dataloggingDev`, `dataloggingTest`
- **Role:** `ic_manager_role` — `SELECT` on `SCHEMA::[icm]` (reads) + `EXECUTE` on each write proc (writes)
- **App user:** `db_ic_manager_user` (contained user, member of the role)

The app **reads** tables directly and **writes only through stored procedures** —
it has no direct INSERT/UPDATE/DELETE. Ownership chaining means `EXECUTE` on the
procs is sufficient; the role needs no table-level DML. EXECUTE is granted
**per procedure** (not schema-wide), so a new write proc isn't runnable until its
`GRANT` is added. Procs `007`–`009` are granted together in `010`; procs added
**after** `010` grant themselves in their own migration (the files are
append-only, so `010` is never edited again).

## Files (run in order)

| # | File | Creates |
|---|------|---------|
| 001 | `001_create_schema_and_ledger.sql` | `icm` schema + `icm.schema_migrations` ledger |
| 002 | `002_create_role_ic_manager_role.sql` | role `ic_manager_role` + `SELECT` grant on `[icm]` |
| 003 | `003_create_user_db_ic_manager_user.sql` | contained user `db_ic_manager_user`, added to the role |
| 004 | `004_create_projects_table.sql` | `icm.projects` |
| 005 | `005_create_cells_table.sql` | `icm.cells` (FK → projects) |
| 006 | `006_create_channel_history_table.sql` | `icm.channel_history` (FK → projects) |
| 007 | `007_create_cell_procedures.sql` | `usp_cell_insert` / `_update` / `_delete` |
| 008 | `008_create_project_procedures.sql` | `usp_project_insert` / `_update` / `_rename` / `_delete` |
| 009 | `009_create_history_procedures.sql` | `usp_history_insert` / `_update` |
| 010 | `010_grant_execute_to_role.sql` | `EXECUTE` on each write proc (007–009) to the role |
| 011 | `011_create_history_delete_procedure.sql` | `usp_history_delete` (+ its own `EXECUTE` grant) |
| 012 | `012_create_history_filename_exists_procedure.sql` | `usp_history_filename_exists` (data_filename uniqueness check; + its own `EXECUTE` grant) |
| 013 | `013_add_expected_end_date.sql` | adds `expected_end_date` to `cells` + `channel_history`; updates the 4 insert/update procs |
| 014 | `014_create_calibration_table_and_procs.sql` | `icm.channel_calibration` + `usp_calibration_insert` / `_update` / `_set_decision` / `_delete` (+ their own `EXECUTE` grants) |
| 015 | `015_add_project_density_fe_ppm.sql` | adds `density` + `fe_ppm` to `projects`; updates `usp_project_insert` / `_update` (for auto data-filename generation) |

## How to run

1. Connect SSMS / Azure Data Studio to the target database (apply to **`dataloggingTest`** first, `dataloggingDev` after).
2. Run `001` → `015` in order. Each file is safe to re-run.
3. For `003`, set a real password in `@pw` first, run, then **close without saving**.
4. Confirm: `SELECT * FROM icm.schema_migrations ORDER BY id;`

## Seeding initial data (after migrations)

Run the loader to seed `icm.cells` from `immersion_cells_template.csv`
(`projects` and `channel_history` start empty by design):

```
python -m src.data.sql.load_initial_data            # load the template
python -m src.data.sql.load_initial_data --dry-run  # preview, no changes
```

It **prompts** for the connection: pick the database (`dataloggingTest` /
`dataloggingDev`), then type the server, username, and password (hidden). It
guards on the chosen database name and only inserts channels that aren't already
present (safe to re-run). Use a privileged login — `ic_manager_role` may not have
INSERT rights.

## Resetting (test only)

`../reset_dev.sql` drops the three domain tables so the migrations can recreate
them after a schema change. It is **destructive** and guarded to run **only on
`dataloggingTest`** (it throws on `dataloggingDev` / anything else). After
running it, re-run `004`–`006`.

## Notes

- Every table uses a surrogate `id INT IDENTITY` primary key. The business keys —
  `projects.project_id` (name) and `cells.channel` — are `UNIQUE NOT NULL` columns;
  the FKs reference those unique business keys (so project rename still cascades).
- `db_ic_manager_user`'s password is typed at run time in `003` and never saved to source
  control; store it in the app config later (used by pyodbc).
- `cells.duration` is **not** stored; the app computes it from `start_date` + `start_hour`.
- `channel_history.channel` is **not** a FK to `cells` (history outlives a deleted cell).
- Azure SQL can't `BULK INSERT` local files, which is why seeding goes through the
  Python loader (`src/data/sql/load_initial_data.py`) rather than a `.sql` file.
