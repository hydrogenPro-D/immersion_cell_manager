# Immersion Cell Manager

A Windows desktop app for running the immersion cell test station. It keeps track of
which channel holds which cell and experiment, the history of every channel, channel
calibrations, the IC Logbook of finished experiments, the consumables inventory, the
event log, and the queue of planned experiments.

Everyone works on the same shared database (Azure SQL), so a change one person makes
shows up for everybody else within a few seconds.

- [Using the app](#using-the-app)
- [Local setup](#local-setup)
- [Architecture](#architecture)
- [SQL migrations](#sql-migrations)
- [Testing](#testing)
- [Versioning](#versioning)
- [Building the exe](#building-the-exe)

---

## Using the app

### Installing and starting

1. Copy the whole `Immersion Cell Manager` release folder to your PC (keep the folder
   together, the exe needs the `_internal` folder next to it).
2. Start `Immersion Cell Manager.exe`.
3. On the first start, if the Microsoft ODBC Driver 18 for SQL Server is missing, the
   app opens its installer. Finish the installation and start the app again.

The window title shows the version you are running, for example `v1.0`.

### Tabs

| Tab | What it is for |
|---|---|
| **Cells mapping** | The live state of every channel: status (Available, In use, In repair, Test finished), project, cathode and anode, start date and time, expected end, data filename. Double-click a row to edit it, add or remove channels, and manage the project list (name, color, description). When a test is finished, the app offers to record it in the IC Logbook. |
| **Station Summary** | A timeline with one row per channel and a bar for each experiment it has run, colored by project. Double-click a bar to see its details, edit it or delete it. |
| **Channel Calibration** | The latest calibration of every channel, with the deviation at each of the six reference resistances. Double-click a channel to see its history and plot, add a measurement, and approve or reject it. |
| **IC Logbook** | All finished experiments, one sub-tab per project, plus a **Summary** sub-tab with total testing time, experiment counts per project and the scoreboard. Experiments can be added, edited and moved between projects; projects can be added, renamed and archived. |
| **Inventory** | Consumables in stock. Set how many cells to plan for, and each item shows what is still needed (red while short). |
| **Event Log** | A record of events (for example a calibration or a cell rebuild) and the items each one used up. Logging an event subtracts its items from the inventory. Pick an event type, or type a new name to log a one-time event and choose its items yourself. **Manage event types** sets up the reusable events and what they use. |
| **Experiment planning** | Requests for new experiments. A new plan waits in **Approval pending**; once approved it moves to **Scheduled**, where rows can be dragged into order. Loading a scheduled plan opens the Cells mapping editor with its details filled in. |

---

## Local setup

Requirements: Windows, Python 3.14, and access to the Azure SQL server.

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Database settings live in `config/`. They are git-ignored because they hold the
password:

| File | Used by | Database |
|---|---|---|
| `config/db_config.json` | running from source, test builds | `dataloggingTest` |
| `config/db_config.prod.json` | production builds, `load_to_db.py --prod` | `dataloggingDev` |

Create them from `config/db_config.example.json` and fill in the server, database,
user and password. Then run the app:

```powershell
python main.py
```

VS Code has a ready debug configuration (**Python Debugger: main.py**). If the ODBC
driver is missing, `driver/msodbcsql.msi` installs it.

---

## Architecture

```
main.py              splash screen, then loads everything on a worker thread
  src/gui/           PyQt6 tabs, dialogs and widgets (one module per tab)
  src/data/          managers: one per tab, all data rules live here
    db.py            the only code that talks to the database (pyodbc)
      Azure SQL      schema icm: tables + usp_* stored procedures
```

Rules the code follows:

- **Reads use SELECT, writes go through stored procedures.** The app login
  (`db_ic_manager_user`, role `ic_manager_role`) can read the `icm` schema and run
  the `usp_*` procs, nothing else. A write that needs several steps is one proc, so
  it happens in one transaction.
- **Managers hold no Qt objects.** `main.py` creates them on a background thread
  while the splash pulses, then hands them to the GUI. The managers can be tested
  without a window.
- **The GUI does not know where data comes from.** Tabs only call their manager
  (`ImmersionCellsManager`, `StationSummaryManager`, `CalibrationManager`,
  `LogbookManager`, `InventoryManager`, `EventLogManager`,
  `ExperimentPlanManager`, `ProjectsManager`).
- **Multi-user refresh.** `DatabaseChangeNotifier` (in `db.py`) checks a cheap
  fingerprint of every `icm` table every 5 seconds and reloads only the tabs whose
  tables changed. The app's own writes don't trigger a second reload.

Folder layout:

| Path | Contents |
|---|---|
| `main.py` | Entry point |
| `src/splash.py` | Startup splash, icon paths, Windows taskbar identity |
| `src/app_version.py` | Reads and bumps `config/version.json` |
| `src/gui/` | Tabs (`cells_mapping.py`, `station_summary_gui.py`, ...), `styles/`, `widgets/` |
| `src/data/` | Managers, `db.py`, `enums.py` |
| `src/data/sql/migrations/` | Numbered SQL migrations |
| `src/data/sql/load_initial_data.py` | Seeds the 60 channels into a new database |
| `src/data/logbook_export/` | Excel to database import for the IC Logbook (see `ic_logbook_processing.md`) |
| `config/` | DB settings (git-ignored), `calibration_config.json`, `version.json` |
| `driver/` | Bundled ODBC driver installer |
| `assets/` | App icons |
| `tools/` | Build script, PyInstaller spec, icon generators |

---

## SQL migrations

The schema is built by numbered SQL files in `src/data/sql/migrations/`, run by
hand in SSMS or Azure Data Studio. There is no migration tool. Full conventions:
[`src/data/sql/integration/MIGRATION_PLAYBOOK.md`](src/data/sql/integration/MIGRATION_PLAYBOOK.md);
the list of files and what each creates:
[`src/data/sql/migrations/README.md`](src/data/sql/migrations/README.md).

Databases:

| Database | Role |
|---|---|
| `dataloggingTest` | Test. Every migration goes here first. |
| `dataloggingDev` | **Production** (despite the name). |

### Running migrations

1. Connect to the target database with an admin login.
2. Run the new files in number order, on `dataloggingTest` first, then
   `dataloggingDev`.
3. Check what has been applied:
   ```sql
   SELECT * FROM icm.schema_migrations ORDER BY id;
   ```

Every file is safe to run again: it only creates what is missing.

### Writing a new migration

- Name it with the next number: `024_short_description.sql`.
- **Never edit a file that has already run anywhere.** Fix or extend it with a new file.
- Keep the whole file one batch, with a single `GO` at the very end, so a failed
  guard stops the entire file.
- Start with the database guard and a check that the previous migration ran:
  ```sql
  IF DB_NAME() NOT IN (N'dataloggingDev', N'dataloggingTest')
      THROW 50000, N'Refusing to run: not an expected database.', 1;
  ```
- Make every step conditional (`IF OBJECT_ID(...) IS NULL`, `IF COL_LENGTH(...) IS NULL`,
  `CREATE OR ALTER PROCEDURE`).
- For a new write proc, add `GRANT EXECUTE ON OBJECT::[icm].[usp_...] TO [ic_manager_role];`
  in the same file, or the app can't call it.
- End by recording the file in `icm.schema_migrations`.
- Add a row to the table in `src/data/sql/migrations/README.md`.

Ship the migration to production **before** the app version that needs it.

---

## Testing

Unit tests use the standard `unittest` module and need no database:

```powershell
python -m unittest
```

| Tests | Cover |
|---|---|
| `src/tests/test_app_version.py` | Version file reading and bumping, the build script's version prompts |
| `src/tests/test_startup.py` | Splash and icon wiring (for example, the splash must not import the GUI) |
| `src/data/tests/` | Manager logic that runs without a database |
| `src/gui/tests/` | Table widget sorting helpers |

Anything that touches the database is tested by hand against `dataloggingTest`:
run from source (it uses `config/db_config.json`), or make a test build (see below)
and try it on another PC. Production data is never used for testing.

---

## Versioning

- The version is `major.minor` (`1.0`, `1.1`, ... `1.10`), stored with its release
  time in `config/version.json`, which is committed.
- Only a **production** build bumps it, and only after you confirm (`1.0` -> `1.1`).
  A test build keeps the current number. For a major release (`2.0`), edit
  `config/version.json` by hand before the build.
- The window title shows the version. Running from source without the file shows
  `dev`.
- After a production build, commit the updated `config/version.json`.

---

## Building the exe

The app is packaged with PyInstaller as a folder (not a single file):

```powershell
python tools/generate_executable.py
```

The script asks everything before the slow build starts:

1. **Production or test build? [p/T]**
   - `p` ships `config/db_config.prod.json` (production database). The build stops
     if that file is missing or points at `dataloggingTest`.
   - Anything else ships `config/db_config.json` (test database).
   - The script prints which database the build will connect to. Check it.
2. **Bump the version? [y/N]** (production builds only, see [Versioning](#versioning)).

The output is `dist/Immersion Cell Manager/`. Next to the exe, `_internal/` holds the
Python runtime plus:

- `config/` with the chosen settings as `db_config.json`, plus `version.json` and
  `calibration_config.json`;
- `driver/` with the ODBC driver installer;
- `assets/` with the icons.

The PyInstaller settings are in `tools/Immersion Cell Manager.spec`. If you delete
the spec, the script generates a new one.

Release steps:

1. Apply any new migrations to `dataloggingTest`, test, then apply them to `dataloggingDev`.
2. Run the build, answer `p`, check the printed database is `dataloggingDev`, and bump the version.
3. Start the exe from `dist/` and check the tabs load.
4. Share the whole `Immersion Cell Manager` folder.
5. Commit `config/version.json`.

The built folder contains the database password in `_internal/config/db_config.json`.
Share it only inside the company.
