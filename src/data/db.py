"""Database access layer (pyodbc) for the ``icm`` schema.

Reads go through ``SELECT`` (the app role has SELECT on the schema); every write
goes through an ``icm.usp_*`` stored procedure (the role has EXECUTE on those,
no direct DML). Connection settings come from ``config/db_config.json`` (copy
``config/db_config.example.json`` and fill it in).

``pyodbc`` is imported lazily inside the methods that touch the database, so the
managers' non-DB logic (column mappings, etc.) and the unit tests can run
without the driver installed.
"""

import json
import subprocess
import time
from datetime import date, datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

# Project root: src/data/db.py -> parents[2]. In the frozen build this resolves
# to the PyInstaller ``_internal`` directory, where the build copies ``config/``
# and ``driver/`` (see tools/generate_executable.py).
_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "db_config.json"
_REQUIRED_KEYS = ("server", "database", "username", "password")
_DEFAULT_DRIVER = "ODBC Driver 18 for SQL Server"

# Bundled ODBC driver installer, used when the driver isn't installed yet.
_DRIVER_DIR = _ROOT / "driver"
_driver_install_attempted = False


class DatabaseError(RuntimeError):
    """Raised for any configuration or database access failure."""


# SQLSTATEs meaning the link is gone (vs. an error in the statement itself).
_CONNECTION_STATES = ("08S01", "08001", "08003", "08004", "08007", "HYT00", "HYT01")
_IDLE_PING_S = 300   # check a connection idle this long before using it
_QUERY_TIMEOUT_S = 30
_LOGIN_TIMEOUT_S = 15


def _is_connection_error(error) -> bool:
    return bool(getattr(error, "args", None)) and str(error.args[0]) in _CONNECTION_STATES


def to_text(value) -> str:
    """Render a DB value the way the old file backend did, as a string.

    ``None`` becomes ``""`` and dates become ``YYYY-MM-DD`` so all the existing
    string-based parsing/formatting in the managers keeps working unchanged.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def to_param(value):
    """Normalize a UI value for a stored-proc parameter: ``""`` -> ``None``.

    Empty strings become SQL ``NULL`` (important for ``project_id``, whose FK
    rejects ``""``, and for nullable date/number columns).
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _find_driver_installer() -> Path | None:
    """Return the bundled ODBC driver installer, or None if not present."""
    if not _DRIVER_DIR.is_dir():
        return None
    preferred = _DRIVER_DIR / "msodbcsql.msi"
    if preferred.exists():
        return preferred
    for pattern in ("*.msi", "*.exe"):
        found = sorted(_DRIVER_DIR.glob(pattern))
        if found:
            return found[0]
    return None


def ensure_driver(driver_name: str) -> None:
    """Make sure the ODBC ``driver_name`` is installed.

    If it isn't, launch the bundled installer (``driver/msodbcsql.msi``) and
    wait for it to finish, then re-check, instead of letting the connection
    crash with a cryptic 'driver not found'. Raises :class:`DatabaseError` if
    no installer is available or the driver is still missing afterward.
    """
    import pyodbc

    if driver_name in pyodbc.drivers():
        return

    global _driver_install_attempted
    if _driver_install_attempted:
        raise DatabaseError(
            f"ODBC driver '{driver_name}' is not installed. "
            "Please install it and restart the app."
        )
    _driver_install_attempted = True

    installer = _find_driver_installer()
    if installer is None:
        raise DatabaseError(
            f"ODBC driver '{driver_name}' is not installed and no installer was "
            f"found in {_DRIVER_DIR}."
        )

    print(f"ODBC driver '{driver_name}' not found, launching installer "
          f"{installer.name}; please complete the installation...")
    try:
        if installer.suffix.lower() == ".msi":
            # msiexec shows the wizard and prompts for elevation if needed;
            # run() blocks until the install finishes or is cancelled.
            subprocess.run(["msiexec", "/i", str(installer)], check=False)
        else:
            subprocess.run([str(installer)], check=False)
    except OSError as e:
        raise DatabaseError(f"Could not launch the driver installer {installer}: {e}")

    if driver_name not in pyodbc.drivers():
        raise DatabaseError(
            f"ODBC driver '{driver_name}' is still not available after running "
            f"{installer.name}. If you just installed it, please restart the app."
        )
    print(f"ODBC driver '{driver_name}' installed, continuing.")


class Database:
    """A single, lazily-opened pyodbc connection with reconnect-on-failure."""

    def __init__(self, config_path: Path = None):
        self._config_path = Path(config_path) if config_path else _CONFIG_PATH
        self._config = None
        self._conn = None
        self._last_used = 0.0
        self._write_listeners = []  # called with the proc name after each write

    # ------------------------------------------------------ config / connect
    def _load_config(self) -> dict:
        if self._config is not None:
            return self._config
        if not self._config_path.exists():
            raise DatabaseError(
                f"Database config not found at {self._config_path}.\n"
                "Copy config/db_config.example.json to config/db_config.json "
                "and fill it in."
            )
        try:
            cfg = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise DatabaseError(f"Could not read {self._config_path}: {e}")
        missing = [k for k in _REQUIRED_KEYS if not cfg.get(k)]
        if missing:
            raise DatabaseError(
                f"db_config.json is missing required keys: {', '.join(missing)}"
            )
        self._config = cfg
        return cfg

    def _connection_string(self) -> str:
        cfg = self._load_config()
        return (
            f"DRIVER={{{cfg.get('driver', _DEFAULT_DRIVER)}}};"
            f"SERVER={cfg['server']};DATABASE={cfg['database']};"
            f"UID={cfg['username']};PWD={cfg['password']};"
        )

    def _get_conn(self):
        import pyodbc
        if self._conn is not None:
            # Ping only after a long idle (Azure drops idle links); pinging
            # before every query doubled the round trips.
            if time.monotonic() - self._last_used > _IDLE_PING_S:
                try:
                    self._conn.cursor().execute("SELECT 1")
                except pyodbc.Error:
                    self._drop_conn()
        if self._conn is None:
            # Make sure the ODBC driver exists (install it from driver/ if not)
            # before attempting to connect.
            ensure_driver(self._load_config().get("driver", _DEFAULT_DRIVER))
            try:
                self._conn = pyodbc.connect(self._connection_string(), autocommit=True,
                                            timeout=_LOGIN_TIMEOUT_S)
                # Per-query limit, so a stalled link can't freeze the UI forever.
                self._conn.timeout = _QUERY_TIMEOUT_S
            except pyodbc.Error as e:
                raise DatabaseError(f"Could not connect to the database: {e}")
        self._last_used = time.monotonic()
        return self._conn

    def _drop_conn(self) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    def add_write_listener(self, callback) -> None:
        """``callback(proc_name)`` runs after every successful write."""
        self._write_listeners.append(callback)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ------------------------------------------------------------------ API
    def fetch_all(self, sql: str, params=()) -> list[dict]:
        """Run a SELECT and return rows as dicts keyed by column name."""
        import pyodbc
        for attempt in (1, 2):
            try:
                cur = self._get_conn().cursor()
                cur.execute(sql, params) if params else cur.execute(sql)
                columns = [c[0] for c in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
            except pyodbc.Error as e:
                if attempt == 1 and _is_connection_error(e):
                    self._drop_conn()  # stale link: reconnect once (reads are safe to repeat)
                    continue
                raise DatabaseError(f"Query failed: {e}")

    def fetch_row(self, sql: str, params=()) -> dict | None:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def exec_proc(self, proc: str, params: dict = None, returns_id: bool = False):
        """Call an ``icm.usp_*`` procedure with named parameters.

        With ``returns_id=True`` the proc's ``@id OUTPUT`` is captured and
        returned (used by ``usp_history_insert``).
        """
        import pyodbc
        params = params or {}
        names = list(params.keys())
        values = [params[n] for n in names]
        assignments = ", ".join(f"@{n} = ?" for n in names)
        try:
            cur = self._get_conn().cursor()
            if returns_id:
                sep = ", " if assignments else ""
                sql = (
                    "SET NOCOUNT ON; DECLARE @new_id INT; "
                    f"EXEC [icm].[{proc}] {assignments}{sep}@id = @new_id OUTPUT; "
                    "SELECT @new_id;"
                )
                cur.execute(sql, values)
                row = None
                while True:
                    if cur.description is not None:
                        row = cur.fetchone()
                        break
                    if not cur.nextset():
                        break
                result = int(row[0]) if row and row[0] is not None else None
            else:
                cur.execute(f"EXEC [icm].[{proc}] {assignments}", values)
                result = None
        except pyodbc.Error as e:
            if _is_connection_error(e):
                self._drop_conn()  # reconnect next time; a write is never retried blindly
            raise DatabaseError(f"Procedure {proc} failed: {e}")
        for callback in self._write_listeners:
            callback(proc)
        return result


# Process-wide shared connection (the app is single-threaded on the Qt main loop).
_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db


# Tables an app write already re-reads itself (the tab reloads right after the
# write); the poll re-baselines them so it doesn't reload them a second time.
_SELF_REFRESHING = (
    ("usp_inventory_", ("inventory_item", "inventory_config", "event_type_cost")),
    ("usp_event_", ("event_type", "event_type_cost", "event_log", "event_log_cost",
                    "inventory_item")),
    ("usp_ic_logbook_", ("ic_logbook", "ic_logbook_value", "ic_logbook_project",
                         "ic_logbook_project_column", "ic_logbook_scoreboard")),
)


class DatabaseChangeNotifier(QObject):
    """Polls a cheap per-table fingerprint of every ``icm`` table and emits
    ``changed`` with the set of tables that moved, so the UI refreshes when
    another user writes through the database."""

    changed = pyqtSignal(object)  # set of table names

    def __init__(self, db: Database = None, interval_ms: int = 5000, parent=None):
        super().__init__(parent)
        self._db = db or get_db()
        self._sql = None
        self._fingerprint = None
        self._own_tables = set()  # written by this app, awaiting a re-baseline
        self._db.add_write_listener(self._on_own_write)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check)
        self._timer.start(interval_ms)

    def _build_sql(self) -> str:
        # COUNT catches inserts/deletes; BINARY_CHECKSUM also catches case-only edits.
        names = [r["name"] for r in self._db.fetch_all(
            "SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID('icm')"
            " AND name <> 'schema_migrations' ORDER BY name")]
        parts = []
        for n in names:
            parts.append(f"(SELECT COUNT(*) FROM icm.[{n}]) AS [{n}|count]")
            parts.append(f"(SELECT ISNULL(CHECKSUM_AGG(BINARY_CHECKSUM(*)), 0)"
                         f" FROM icm.[{n}]) AS [{n}|sum]")
        return "SELECT " + ", ".join(parts)

    def _read(self):
        """{table: (count, checksum)}, or None on a transient failure."""
        try:
            if self._sql is None:
                self._sql = self._build_sql()
            row = self._db.fetch_row(self._sql)
        except DatabaseError:
            self._sql = None  # e.g. a table changed by a migration: rebuild next time
            return None
        fp = {}
        for key, value in (row or {}).items():
            table, part = key.split("|")
            fp.setdefault(table, [None, None])[0 if part == "count" else 1] = value
        return {t: tuple(v) for t, v in fp.items()}

    def _on_own_write(self, proc: str) -> None:
        tables = {t for prefix, ts in _SELF_REFRESHING if proc.startswith(prefix) for t in ts}
        if tables:
            if not self._own_tables:
                # After the current click finishes (the tab has re-read by then).
                QTimer.singleShot(0, self._rebaseline)
            self._own_tables |= tables

    def _rebaseline(self) -> None:
        own, self._own_tables = self._own_tables, set()
        fingerprint = self._read() if self._fingerprint is not None else None
        if fingerprint is not None:
            for t in own & fingerprint.keys():
                self._fingerprint[t] = fingerprint[t]

    def _check(self) -> None:
        fingerprint = self._read()
        if fingerprint is None:
            return  # transient; try again next tick
        if self._fingerprint is None:
            self._fingerprint = fingerprint
            return
        # A table new since the baseline (a migration) has nothing to compare with.
        changed = {t for t in fingerprint
                   if t in self._fingerprint and fingerprint[t] != self._fingerprint[t]}
        self._fingerprint = fingerprint
        if changed:
            self.changed.emit(changed)

    def stop(self) -> None:
        self._timer.stop()
