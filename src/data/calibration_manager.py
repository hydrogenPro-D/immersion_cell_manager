"""Manager for channel calibration measurements.

Each channel is calibrated by driving a known current through six reference
resistances and reading the potential. The app derives, per resistance R:

    ΔV% = 100 * (measured - I*R) / (I*R)          (I*R is the theoretical value)

and auto-evaluates whether all six fall inside the acceptance band. A human then
Approves/Rejects (the stored ``decision``); the band + default current live in
``config/calibration_config.json``.

Backed by ``icm.channel_calibration``: reads via SELECT, writes via the
``icm.usp_calibration_*`` procedures. Channels mirror ``icm.cells``.
"""

import json
from datetime import date, datetime
from pathlib import Path

from src.data.db import get_db, DatabaseError, to_text, to_param

# Project root: src/data/calibration_manager.py -> parents[2]. In the frozen
# build this resolves to the PyInstaller _internal dir, where config/ is copied.
_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "calibration_config.json"

# Fallback spec if the config file is missing/unreadable (keeps the tab usable).
_DEFAULT_SPEC = {
    "applied_current_default": 0.92,
    "resistances": [1.0, 1.5, 2.0, 3.3, 4.0, 5.0],
    "bounds": {
        "1.0": {"min": 0.11, "max": 0.27},
        "1.5": {"min": -0.36, "max": -0.22},
        "2.0": {"min": -0.93, "max": -0.82},
        "3.3": {"min": -0.40, "max": -0.30},
        "4.0": {"min": -0.79, "max": -0.64},
        "5.0": {"min": -0.76, "max": -0.61},
    },
}

# DB columns, in order, and the six potential columns keyed by resistance.
POTENTIAL_COLUMNS = ["p_1_0", "p_1_5", "p_2_0", "p_3_3", "p_4_0", "p_5_0"]
CALIB_COLUMNS = [
    "id", "channel", "measured_date", "ic_number", "measured_by",
    "applied_current", *POTENTIAL_COLUMNS, "decision", "decided_by",
    "decided_at", "note",
]

# Display statuses.
STATUS_READY = "Ready to test"
STATUS_AWAITING = "Awaiting decision"
STATUS_PASS = "Pass"
STATUS_FAIL = "Fail"
STATUS_IN_USE = "In use"

# Cell statuses that block calibration (an experiment is running on the channel).
LOCKED_CELL_STATUSES = ("in use",)

# A calibration older than this many days is "stale": the channel can't be set
# In use until it's re-tested. Never-tested channels (no date) are NOT stale.
MAX_CALIBRATION_AGE_DAYS = 90


def _to_float(value):
    """Parse a float from a string/number, or None if blank/invalid."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_float(value):
    """Public: parse a float accepting ',' or '.' as the decimal separator.

    Returns None for blank/invalid input (used by the UI to validate entries).
    """
    return _to_float(value)


class CalibrationManager:
    """Reads/writes channel calibration measurements and evaluates them."""

    def __init__(self, db=None):
        self._db = db or get_db()
        self._spec = self._load_spec()

    # ----------------------------------------------------------- Config / spec
    @staticmethod
    def _load_spec() -> dict:
        try:
            spec = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(_DEFAULT_SPEC)
        # Fill any missing keys from the defaults so a partial file still works.
        for key, val in _DEFAULT_SPEC.items():
            spec.setdefault(key, val)
        return spec

    def resistances(self) -> list:
        """The six reference resistances (ohm), in column order."""
        return [float(r) for r in self._spec.get("resistances", [])]

    def applied_current_default(self) -> float:
        return float(self._spec.get("applied_current_default", 0.92))

    def bounds(self) -> list:
        """Return ``[(min, max), ...]`` aligned with :meth:`resistances`."""
        raw = self._spec.get("bounds", {})
        out = []
        for r in self.resistances():
            # Bounds keys are strings like "1.0" / "3.3".
            entry = raw.get(self._res_key(r)) or {}
            out.append((entry.get("min"), entry.get("max")))
        return out

    @staticmethod
    def _res_key(r: float) -> str:
        """Config key for a resistance (e.g. 1.0 -> '1.0', 3.3 -> '3.3')."""
        return f"{r:.1f}"

    # ------------------------------------------------------------- Computation
    def delta_percent(self, applied_current, potentials: list) -> list:
        """Return the six ΔV% values (or None where a reading is missing).

        ΔV% = 100 * (measured - I*R) / (I*R); if the current is 0 the result is 0
        (matching the source spreadsheet).
        """
        current = _to_float(applied_current)
        deltas = []
        for r, p in zip(self.resistances(), potentials):
            pv = _to_float(p)
            if pv is None or current is None:
                deltas.append(None)
            elif current == 0:
                deltas.append(0.0)
            else:
                theoretical = current * r
                deltas.append(100.0 * (pv - theoretical) / theoretical)
        return deltas

    def evaluate(self, deltas: list) -> str:
        """Auto-suggested verdict from the deltas: 'pass' | 'fail' | 'incomplete'.

        'incomplete' means not all six readings are present, so no verdict yet.
        """
        if any(d is None for d in deltas) or len(deltas) < len(self.resistances()):
            return "incomplete"
        for d, (lo, hi) in zip(deltas, self.bounds()):
            if lo is not None and d < lo:
                return "fail"
            if hi is not None and d > hi:
                return "fail"
        return "pass"

    # --------------------------------------------------------------- Records
    def _record(self, row: dict) -> dict:
        """Turn a DB row into a display record with derived deltas + status."""
        potentials = [row.get(c) for c in POTENTIAL_COLUMNS]
        deltas = self.delta_percent(row.get("applied_current"), potentials)
        decision = (to_text(row.get("decision")) or "").strip()
        status = decision if decision in (STATUS_PASS, STATUS_FAIL) else STATUS_AWAITING
        return {
            "id": int(row["id"]) if row.get("id") is not None else None,
            "channel": to_text(row.get("channel")),
            "measured_date": to_text(row.get("measured_date")),
            "ic_number": to_text(row.get("ic_number")),
            "measured_by": to_text(row.get("measured_by")),
            "applied_current": _to_float(row.get("applied_current")),
            "potentials": [_to_float(p) for p in potentials],
            "deltas": deltas,
            "decision": decision or STATUS_AWAITING,
            "decided_by": to_text(row.get("decided_by")),
            "auto_eval": self.evaluate(deltas),   # 'pass' | 'fail' | 'incomplete'
            "status": status,
            "note": to_text(row.get("note")),
        }

    def get_channels(self) -> list:
        """Channels to calibrate — mirrors the immersion cells (in id order)."""
        try:
            rows = self._db.fetch_all("SELECT channel FROM icm.cells ORDER BY id")
        except DatabaseError:
            return []
        return [to_text(r.get("channel")) for r in rows if to_text(r.get("channel"))]

    def get_latest_per_channel(self) -> list:
        """One summary record per channel (its most recent measurement).

        Channels with no measurement yet get a placeholder 'Ready to test' record.
        """
        columns = ", ".join(CALIB_COLUMNS)
        try:
            rows = self._db.fetch_all(
                f"SELECT {columns} FROM ("
                f"  SELECT {columns}, ROW_NUMBER() OVER ("
                "     PARTITION BY channel ORDER BY measured_date DESC, id DESC) AS rn"
                "  FROM icm.channel_calibration) t WHERE rn = 1"
            )
        except DatabaseError:
            rows = []  # table not migrated yet — every channel shows Ready to test
        latest = {to_text(r.get("channel")): self._record(r) for r in rows}

        # Channels + current cell status come from icm.cells (one query).
        try:
            cells = self._db.fetch_all(
                "SELECT channel, status FROM icm.cells ORDER BY id"
            )
        except DatabaseError:
            cells = []

        records = []
        for r in cells:
            channel = to_text(r.get("channel"))
            if not channel:
                continue
            rec = latest.get(channel) or self._empty_record(channel)
            self._apply_cell_status(rec, to_text(r.get("status")))
            records.append(rec)
        return records

    def _apply_cell_status(self, rec: dict, cell_status: str) -> None:
        """Overlay the cell's current status: In use locks calibration."""
        rec["cell_status"] = cell_status
        locked = (cell_status or "").strip().lower() in LOCKED_CELL_STATUSES
        rec["locked"] = locked
        if locked:
            rec["status"] = STATUS_IN_USE  # can't calibrate a running cell

    def is_locked(self, channel: str) -> bool:
        """True if the channel's cell is In use, so calibration is blocked."""
        try:
            row = self._db.fetch_row(
                "SELECT status FROM icm.cells WHERE channel = ?", (channel,)
            )
        except DatabaseError:
            return False
        status = to_text(row.get("status")) if row else ""
        return status.strip().lower() in LOCKED_CELL_STATUSES

    # ------------------------------------------------------- Calibration age
    @staticmethod
    def age_days(measured_date: str):
        """Days since ``measured_date`` (``yyyy-MM-dd``), or None if empty/bad."""
        text = (measured_date or "").strip()[:10]
        if not text:
            return None
        try:
            d = datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None
        return (date.today() - d).days

    @classmethod
    def is_stale_date(cls, measured_date: str) -> bool:
        """True if there is a date and it's older than the max age (blocks In use)."""
        age = cls.age_days(measured_date)
        return age is not None and age >= cls.MAX_AGE_DAYS

    MAX_AGE_DAYS = MAX_CALIBRATION_AGE_DAYS

    def get_stale_channels(self) -> set:
        """Channels whose latest calibration is older than the max age."""
        return {rec["channel"] for rec in self.get_latest_per_channel()
                if self.is_stale_date(rec["measured_date"])}

    def is_channel_stale(self, channel: str) -> bool:
        """True if this channel's latest calibration is older than the max age."""
        try:
            row = self._db.fetch_row(
                "SELECT TOP 1 measured_date FROM icm.channel_calibration "
                "WHERE channel = ? ORDER BY measured_date DESC, id DESC",
                (channel,),
            )
        except DatabaseError:
            return False
        return self.is_stale_date(to_text(row.get("measured_date"))) if row else False

    def is_channel_pending(self, channel: str) -> bool:
        """True if the channel has a calibration still Awaiting decision."""
        try:
            row = self._db.fetch_row(
                "SELECT TOP 1 id FROM icm.channel_calibration "
                "WHERE channel = ? AND decision = ?",
                (channel, STATUS_AWAITING),
            )
        except DatabaseError:
            return False
        return row is not None

    def get_pending_channels(self) -> set:
        """Channels with a calibration still Awaiting decision."""
        try:
            rows = self._db.fetch_all(
                "SELECT DISTINCT channel FROM icm.channel_calibration "
                "WHERE decision = ?",
                (STATUS_AWAITING,),
            )
        except DatabaseError:
            return set()
        return {to_text(r.get("channel")) for r in rows}

    def is_channel_failed(self, channel: str) -> bool:
        """True if the channel's latest calibration measurement is a Fail."""
        try:
            row = self._db.fetch_row(
                "SELECT TOP 1 decision FROM icm.channel_calibration "
                "WHERE channel = ? ORDER BY measured_date DESC, id DESC",
                (channel,),
            )
        except DatabaseError:
            return False
        return (to_text(row.get("decision")).strip() == STATUS_FAIL) if row else False

    def _empty_record(self, channel: str) -> dict:
        n = len(self.resistances())
        return {
            "id": None, "channel": channel, "measured_date": "", "ic_number": "",
            "measured_by": "", "applied_current": None,
            "potentials": [None] * n, "deltas": [None] * n,
            "decision": "", "decided_by": "", "auto_eval": "incomplete",
            "status": STATUS_READY, "note": "",
        }

    def get_history(self, channel: str) -> list:
        """All measurements for ``channel``, newest first, as display records."""
        columns = ", ".join(CALIB_COLUMNS)
        try:
            rows = self._db.fetch_all(
                f"SELECT {columns} FROM icm.channel_calibration "
                "WHERE channel = ? ORDER BY measured_date DESC, id DESC",
                (channel,),
            )
        except DatabaseError:
            return []  # table not migrated yet
        return [self._record(r) for r in rows]

    # ---------------------------------------------------------------- Writes
    def _measurement_params(self, channel: str, values: dict) -> dict:
        """Map a values dict to the insert/update proc parameters."""
        params = {
            "channel": channel,
            "measured_date": to_param(values.get("measured_date")),
            "ic_number": to_param(values.get("ic_number")),
            "measured_by": to_param(values.get("measured_by")),
            "applied_current": _to_float(values.get("applied_current")),
            "note": to_param(values.get("note")),
        }
        for col in POTENTIAL_COLUMNS:
            params[col] = _to_float(values.get(col))
        return params

    def add_measurement(self, channel: str, values: dict):
        """Insert a new measurement (decision defaults to 'Awaiting decision').

        Returns the new id, or None on failure.
        """
        params = self._measurement_params(channel, values)
        params["decision"] = STATUS_AWAITING
        try:
            return self._db.exec_proc("usp_calibration_insert", params, returns_id=True)
        except DatabaseError as e:
            print(f"Error adding calibration measurement: {e}")
            return None

    def update_measurement(self, measurement_id, channel: str, values: dict,
                           decision: str = STATUS_AWAITING) -> bool:
        """Update a measurement's readings and set its ``decision``.

        Defaults to 'Awaiting decision', but the caller may keep/set a specific
        verdict (Pass/Fail) so editing an already-decided measurement doesn't
        force it back to awaiting.
        """
        params = self._measurement_params(channel, values)
        params["id"] = int(measurement_id)
        params["decision"] = decision
        try:
            self._db.exec_proc("usp_calibration_update", params)
            return True
        except (DatabaseError, ValueError, TypeError) as e:
            print(f"Error updating calibration measurement: {e}")
            return False

    def set_decision(self, measurement_id, decision: str, decided_by: str = None) -> bool:
        """Record a human decision ('Pass' or 'Fail')."""
        try:
            self._db.exec_proc("usp_calibration_set_decision", {
                "id": int(measurement_id),
                "decision": decision,
                "decided_by": to_param(decided_by),
            })
            return True
        except (DatabaseError, ValueError, TypeError) as e:
            print(f"Error setting calibration decision: {e}")
            return False

    def delete_measurement(self, measurement_id) -> bool:
        try:
            self._db.exec_proc("usp_calibration_delete", {"id": int(measurement_id)})
            return True
        except (DatabaseError, ValueError, TypeError) as e:
            print(f"Error deleting calibration measurement: {e}")
            return False
