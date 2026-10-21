"""Manager for the Experiment planning tab.

Reads ``icm.experiment_plan`` (migration 023) and writes through the
``usp_experiment_plan_*`` procs. A plan goes pending -> scheduled -> started;
deleted and started plans stay in the table but are not loaded here.
"""

import json

from src.data.db import get_db, DatabaseError, to_text, to_param, db_message

URGENCIES = ["Low", "Normal", "High", "Urgent"]

# Plan fields the forms edit, in display order: (key, label).
PLAN_FIELDS = [
    ("name", "Name"),
    ("test_length_h", "Test length [h]"),
    ("anode", "Anode"),
    ("cathode", "Cathode"),
    ("protocol", "Protocol"),
    ("project_id", "Project"),
    ("aim", "Aim"),
    ("urgency", "Urgency"),
]

_COLUMNS = ["id", "name", "test_length_h", "anode", "cathode", "protocol", "project_id",
            "aim", "urgency", "channel", "status", "priority", "approved_by",
            "approved_at", "created_at"]


def _hours_text(hours: float) -> str:
    """Plain digits: 10000000, 24.5 (":g" would show 1e+07)."""
    if hours.is_integer():
        return str(int(hours))
    return f"{hours:.6f}".rstrip("0").rstrip(".")


class ExperimentPlanManager:
    """Pending and scheduled experiment plans."""

    def __init__(self, db=None):
        self._db = db or get_db()
        self._plans = []
        self.available = False  # False until migration 023 is run
        self.reload()

    # ------------------------------------------------------------------ IO
    def reload(self) -> None:
        try:
            rows = self._db.fetch_all(
                f"SELECT {', '.join(_COLUMNS)} FROM icm.experiment_plan"
                " WHERE status IN ('pending', 'scheduled')"
                " ORDER BY priority, created_at, id")
            self.available = True
        except DatabaseError:
            rows, self.available = [], False
        self._plans = [self._row(r) for r in rows]

    @staticmethod
    def _row(r: dict) -> dict:
        hours = r.get("test_length_h")
        return {
            "id": r["id"],
            "name": to_text(r.get("name")),
            "test_length_h": "" if hours is None else _hours_text(float(hours)),
            "anode": to_text(r.get("anode")),
            "cathode": to_text(r.get("cathode")),
            "protocol": to_text(r.get("protocol")),
            "project_id": to_text(r.get("project_id")),
            "aim": to_text(r.get("aim")),
            "urgency": to_text(r.get("urgency")) or "Normal",
            "channel": to_text(r.get("channel")),  # "" = any cell
            "status": to_text(r.get("status")),
            "approved_by": to_text(r.get("approved_by")),
            "created_at": to_text(r.get("created_at")),
        }

    # ----------------------------------------------------------- Read API
    def get_pending(self) -> list:
        return [p for p in self._plans if p["status"] == "pending"]

    def get_scheduled(self) -> list:
        """In schedule order (top priority first)."""
        return [p for p in self._plans if p["status"] == "scheduled"]

    def get_plan(self, plan_id):
        return next((p for p in self._plans if p["id"] == plan_id), None)

    def get_recent_values(self, field: str) -> list:
        """Distinct earlier values of ``field``, newest first (dropdown suggestions)."""
        seen, out = set(), []
        for p in sorted(self._plans, key=lambda p: p["id"], reverse=True):
            v = (p.get(field) or "").strip()
            if v and v.lower() not in seen:
                seen.add(v.lower())
                out.append(v)
        return out

    # -------------------------------------------------------------- Writes
    # Each returns "" on success, else a readable error; the list is re-read
    # either way, so it shows what is stored.
    def add_plan(self, values: dict) -> str:
        return self._write("usp_experiment_plan_insert", self._params(values), returns_id=True)

    def update_plan(self, plan_id, values: dict) -> str:
        params = self._params(values)
        params.update(id=int(plan_id), channel=to_param(values.get("channel")))
        return self._write("usp_experiment_plan_update", params)

    def approve(self, plan_id, approved_by: str) -> str:
        return self._write("usp_experiment_plan_approve",
                           {"id": int(plan_id), "approved_by": to_param(approved_by)})

    def unapprove(self, plan_id) -> str:
        return self._write("usp_experiment_plan_unapprove", {"id": int(plan_id)})

    def reorder(self, plan_ids: list) -> str:
        return self._write("usp_experiment_plan_reorder",
                           {"ids": json.dumps([int(i) for i in plan_ids])})

    def delete(self, plan_id) -> str:
        return self._write("usp_experiment_plan_delete", {"id": int(plan_id)})

    def mark_started(self, plan_id, channel: str) -> str:
        return self._write("usp_experiment_plan_start",
                           {"id": int(plan_id), "channel": to_param(channel)})

    def _write(self, proc: str, params: dict, returns_id: bool = False) -> str:
        try:
            self._db.exec_proc(proc, params, returns_id=returns_id)
            return ""
        except DatabaseError as e:
            return db_message(e)
        finally:
            self.reload()

    @staticmethod
    def _params(v: dict) -> dict:
        hours = (v.get("test_length_h") or "").strip().replace(",", ".")
        return {
            "name": to_param(v.get("name")),
            "test_length_h": float(hours) if hours else None,
            "anode": to_param(v.get("anode")),
            "cathode": to_param(v.get("cathode")),
            "protocol": to_param(v.get("protocol")),
            "project_id": to_param(v.get("project_id")),
            "aim": to_param(v.get("aim")),
            "urgency": v.get("urgency") or "Normal",
        }
