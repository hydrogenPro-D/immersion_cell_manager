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
            try:
                self._conn.cursor().execute("SELECT 1")
                return self._conn
            except pyodbc.Error:
                try:
                    self._conn.close()
                except pyodbc.Error:
                    pass
                self._conn = None
        # Make sure the ODBC driver exists (install it from driver/ if not)
        # before attempting to connect.
        ensure_driver(self._load_config().get("driver", _DEFAULT_DRIVER))
        try:
            self._conn = pyodbc.connect(self._connection_string(), autocommit=True)
        except pyodbc.Error as e:
            raise DatabaseError(f"Could not connect to the database: {e}")
        return self._conn

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
        try:
            cur = self._get_conn().cursor()
            cur.execute(sql, params) if params else cur.execute(sql)
            columns = [c[0] for c in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
        except pyodbc.Error as e:
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
                return int(row[0]) if row and row[0] is not None else None
            cur.execute(f"EXEC [icm].[{proc}] {assignments}", values)
            return None
        except pyodbc.Error as e:
            raise DatabaseError(f"Procedure {proc} failed: {e}")


# Process-wide shared connection (the app is single-threaded on the Qt main loop).
_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db


class DatabaseChangeNotifier(QObject):
    """Polls a cheap fingerprint of the data and emits ``changed`` when it moves.

    Replaces the old per-file polling: one query covers all three tables, so the
    UI auto-refreshes when another user writes through the database.
    """

    changed = pyqtSignal()

    # COUNT catches inserts/deletes; CHECKSUM_AGG catches in-place updates.
    _FINGERPRINT_SQL = """
        SELECT
            (SELECT COUNT(*) FROM icm.cells)                                      AS c1,
            (SELECT ISNULL(CHECKSUM_AGG(CHECKSUM(*)), 0) FROM icm.cells)          AS c2,
            (SELECT COUNT(*) FROM icm.channel_history)                            AS c3,
            (SELECT ISNULL(CHECKSUM_AGG(CHECKSUM(*)), 0) FROM icm.channel_history) AS c4,
            (SELECT COUNT(*) FROM icm.projects)                                   AS c5,
            (SELECT ISNULL(CHECKSUM_AGG(CHECKSUM(*)), 0) FROM icm.projects)       AS c6,
            (SELECT COUNT(*) FROM icm.channel_calibration)                         AS c7,
            (SELECT ISNULL(CHECKSUM_AGG(CHECKSUM(*)), 0) FROM icm.channel_calibration) AS c8
    """

    def __init__(self, db: Database = None, interval_ms: int = 5000, parent=None):
        super().__init__(parent)
        self._db = db or get_db()
        self._fingerprint = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check)
        self._timer.start(interval_ms)

    def _check(self) -> None:
        try:
            row = self._db.fetch_row(self._FINGERPRINT_SQL)
        except DatabaseError:
            return  # transient; try again next tick
        fingerprint = tuple(row.values()) if row else None
        if self._fingerprint is None:
            self._fingerprint = fingerprint
            return
        if fingerprint != self._fingerprint:
            self._fingerprint = fingerprint
            self.changed.emit()

    def stop(self) -> None:
        self._timer.stop()
