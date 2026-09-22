"""Manager for the Event Log tab.

Two things live here (migration 018 tables):

* **Event types** (`event_type` + `event_type_cost`) - reusable definitions with a
  default cost recipe ("this event consumes N of item X").
* **Logged events** (`event_log` + `event_log_cost`) - occurrences. Logging copies
  the recipe into a snapshot, resolving each item's default-deduct status, and
  deducts it from the shared inventory (clamped at 0). Deleting can restore it.

Deductions/restores go through :class:`InventoryManager`, which owns the inventory
procs, so both tabs stay in sync.
"""

from src.data.db import get_db, DatabaseError, to_text, to_param


class EventLogManager:
    """Event definitions, their cost recipes, and the log of occurrences."""

    def __init__(self, inventory_manager, db=None):
        self._db = db or get_db()
        self.inventory = inventory_manager
        self._types = []
        self._logs = []
        self.reload()

    # ------------------------------------------------------------------ IO
    def reload(self) -> None:
        try:
            types = self._db.fetch_all(
                "SELECT id, name, description, is_archived"
                " FROM icm.event_type ORDER BY name")
            costs = self._db.fetch_all(
                "SELECT event_type_id, item_id, qty FROM icm.event_type_cost")
            logs = self._db.fetch_all(
                "SELECT id, event_type_id, event_name, person, comment, event_date,"
                " logged_at FROM icm.event_log ORDER BY logged_at DESC, id DESC")
            log_costs = self._db.fetch_all(
                "SELECT event_log_id, item_id, item_name, qty"
                " FROM icm.event_log_cost ORDER BY id")
        except DatabaseError:
            types, costs, logs, log_costs = [], [], [], []

        cost_by_type = {}
        for c in costs:
            cost_by_type.setdefault(c["event_type_id"], []).append(
                {"item_id": c["item_id"], "qty": int(c["qty"] or 0)})
        self._types = [{
            "id": t["id"],
            "name": t["name"] or "",
            "description": to_text(t["description"]),
            "is_archived": bool(t["is_archived"]),
            "costs": cost_by_type.get(t["id"], []),
        } for t in types]

        cost_by_log = {}
        for c in log_costs:
            cost_by_log.setdefault(c["event_log_id"], []).append({
                "item_id": c["item_id"],
                "item_name": c["item_name"] or "",
                "qty": int(c["qty"] or 0),
            })
        self._logs = [{
            "id": lg["id"],
            "event_type_id": lg["event_type_id"],
            "event_name": lg["event_name"] or "",
            "person": to_text(lg["person"]),
            "comment": to_text(lg["comment"]),
            "event_date": to_text(lg["event_date"]),
            "logged_at": to_text(lg["logged_at"]),
            "costs": cost_by_log.get(lg["id"], []),
        } for lg in logs]

    # ----------------------------------------------------------- Read API
    def get_types(self, include_archived: bool = False) -> list:
        return [t for t in self._types
                if include_archived or not t["is_archived"]]

    def get_type(self, type_id):
        return next((t for t in self._types if t["id"] == type_id), None)

    def get_logs(self) -> list:
        return list(self._logs)

    def resolve_costs(self, costs: list) -> list:
        """Turn recipe/log cost lines into displayable lines, resolving each
        item's default-deduct bucket and its current available count.

        Returns dicts: item_id, item_name, status_id, status_name, qty,
        available (current count in that bucket), enough (bool).
        """
        lines = []
        for c in costs:
            item = self.inventory.get_item(c["item_id"])
            qty = int(c.get("qty") or 0)
            if item is None:
                lines.append({
                    "item_id": c["item_id"],
                    "item_name": c.get("item_name") or "(deleted item)",
                    "status_id": c.get("status_id"),
                    "status_name": c.get("status_name") or "",
                    "qty": qty, "available": 0, "enough": False,
                })
                continue
            sid = c.get("status_id") or item["default_status_id"]
            status = next((s for s in item["statuses"] if s["id"] == sid), None)
            if status is None and item["statuses"]:
                status = item["statuses"][0]
                sid = status["id"]
            available = status["count"] if status else 0
            lines.append({
                "item_id": item["id"],
                "item_name": item["name"],
                "status_id": sid,
                "status_name": status["name"] if status else "",
                "qty": qty,
                "available": available,
                "enough": qty <= available,
            })
        return lines

    # --------------------------------------------------------- Type writes
    def add_type(self, name: str, description: str = "") -> int:
        tid = self._db.exec_proc("usp_event_type_insert", {
            "name": to_param(name),
            "description": to_param(description),
        }, returns_id=True)
        self.reload()
        return tid

    def update_type(self, type_id, name: str, description: str = "",
                    is_archived: bool = False) -> None:
        self._db.exec_proc("usp_event_type_update", {
            "id": int(type_id),
            "name": to_param(name),
            "description": to_param(description),
            "is_archived": 1 if is_archived else 0,
        })
        self.reload()

    def delete_type(self, type_id) -> None:
        self._db.exec_proc("usp_event_type_delete", {"id": int(type_id)})
        self.reload()

    def set_type_cost(self, type_id, item_id, qty: int) -> None:
        """Set (or, at qty<=0, remove) one recipe line for an event type."""
        self._db.exec_proc("usp_event_type_cost_set", {
            "event_type_id": int(type_id),
            "item_id": int(item_id),
            "qty": int(qty),
        })
        self.reload()

    # ---------------------------------------------------------- Log writes
    def log_event(self, type_id, event_name: str, person: str, comment: str,
                  event_date: str, cost_lines: list) -> int:
        """Insert a log entry, snapshot its cost lines, and deduct them from
        inventory. ``cost_lines`` are resolved lines (see :meth:`resolve_costs`)."""
        log_id = self._db.exec_proc("usp_event_log_insert", {
            "event_type_id": to_param(type_id),
            "event_name": to_param(event_name),
            "person": to_param(person),
            "comment": to_param(comment),
            "event_date": to_param(event_date),
        }, returns_id=True)
        self._apply_lines(log_id, cost_lines)
        self.inventory.reload()
        self.reload()
        return log_id

    def update_log(self, log_id, person: str, comment: str, event_date: str,
                   cost_lines: list = None) -> None:
        """Update a log entry's metadata; if ``cost_lines`` is given, restore the
        old costs, replace the snapshot, and deduct the new ones."""
        if cost_lines is not None:
            self._restore_log(log_id)
            self._db.exec_proc("usp_event_log_cost_delete_by_log",
                               {"event_log_id": int(log_id)})
            self._apply_lines(log_id, cost_lines)
        self._db.exec_proc("usp_event_log_update", {
            "id": int(log_id),
            "person": to_param(person),
            "comment": to_param(comment),
            "event_date": to_param(event_date),
        })
        self.inventory.reload()
        self.reload()

    def delete_log(self, log_id, restore: bool = True) -> None:
        """Delete a log entry; when ``restore`` add its costed items back first."""
        if restore:
            self._restore_log(log_id)
        self._db.exec_proc("usp_event_log_delete", {"id": int(log_id)})
        self.inventory.reload()
        self.reload()

    # ------------------------------------------------------------- Helpers
    def _apply_lines(self, log_id, cost_lines: list) -> None:
        for line in cost_lines:
            qty = int(line.get("qty") or 0)
            if qty <= 0:
                continue
            self._db.exec_proc("usp_event_log_cost_insert", {
                "event_log_id": int(log_id),
                "item_id": to_param(line.get("item_id")),
                "item_name": to_param(line.get("item_name")),
                "qty": qty,
            }, returns_id=True)
            # Deduct from the item's current deduct bucket (its first usable one).
            sid = line.get("status_id") or self._deduct_bucket(line.get("item_id"))
            if sid is not None:
                self.inventory.deduct(sid, qty)

    def _restore_log(self, log_id) -> None:
        log = next((lg for lg in self._logs if lg["id"] == log_id), None)
        if not log:
            return
        for c in log["costs"]:
            qty = int(c.get("qty") or 0)
            sid = self._deduct_bucket(c.get("item_id"))
            if sid is not None and qty > 0:
                self.inventory.restore(sid, qty)

    def _deduct_bucket(self, item_id):
        """The bucket events deduct from for an item (its first usable), or None."""
        item = self.inventory.get_item(item_id) if item_id is not None else None
        return item["default_status_id"] if item else None
