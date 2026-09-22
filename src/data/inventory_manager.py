"""Manager for the Inventory tab.

Backed by the database: reads ``icm.inventory_item`` / ``icm.inventory_status`` /
``icm.inventory_config`` via SELECT and writes through the ``usp_inventory_*``
procs (migration 018). Derived numbers (usable, total, requirement, need-to-order)
are computed live here, exactly like the source Excel:

    requirement   = per_cell_qty * cell_count
    usable        = sum of status counts flagged usable
    need_to_order = requirement - usable
"""

from src.data.db import get_db, DatabaseError, to_param


class InventoryManager:
    """Reads and edits the inventory items, their status buckets and the config."""

    def __init__(self, db=None):
        self._db = db or get_db()
        self._items = []
        self._cell_count = 70
        self.reload()

    # ------------------------------------------------------------------ IO
    def reload(self) -> None:
        """(Re)load config + items + status buckets from the database."""
        try:
            row = self._db.fetch_row(
                "SELECT cell_count FROM icm.inventory_config WHERE id = 1")
            self._cell_count = int(row["cell_count"]) if row else 70
        except DatabaseError:
            self._cell_count = 70

        try:
            items = self._db.fetch_all(
                "SELECT id, name, per_cell_qty FROM icm.inventory_item ORDER BY id")
            statuses = self._db.fetch_all(
                "SELECT id, item_id, name, count, is_usable"
                " FROM icm.inventory_status ORDER BY id")
        except DatabaseError:
            items, statuses = [], []  # tables not created yet

        by_item = {}
        for s in statuses:
            by_item.setdefault(s["item_id"], []).append({
                "id": s["id"],
                "name": s["name"] or "",
                "count": int(s["count"] or 0),
                "is_usable": bool(s["is_usable"]),
            })
        self._items = [self._item_row(it, by_item.get(it["id"], [])) for it in items]

    def _item_row(self, it: dict, statuses: list) -> dict:
        per_cell = float(it["per_cell_qty"] or 0)
        usable = sum(s["count"] for s in statuses if s["is_usable"])
        total = sum(s["count"] for s in statuses)
        requirement = per_cell * self._cell_count
        # Events deduct from the first usable bucket (or the first bucket if none).
        default = next((s["id"] for s in statuses if s["is_usable"]), None)
        if default is None and statuses:
            default = statuses[0]["id"]
        return {
            "id": it["id"],
            "name": it["name"] or "",
            "per_cell_qty": per_cell,
            "statuses": statuses,
            "usable": usable,
            "total": total,
            "requirement": requirement,
            "need_to_order": requirement - usable,
            "default_status_id": default,
        }

    # ----------------------------------------------------------- Public API
    def get_cell_count(self) -> int:
        return self._cell_count

    def get_items(self) -> list:
        return list(self._items)

    def get_item(self, item_id):
        return next((it for it in self._items if it["id"] == item_id), None)

    # --------------------------------------------------------- Config write
    def set_cell_count(self, cell_count: int) -> None:
        self._db.exec_proc("usp_inventory_config_set",
                           {"cell_count": int(cell_count)})
        self.reload()

    # ----------------------------------------------------------- Item writes
    def add_item(self, name: str, per_cell_qty: float,
                 first_status: str = "In stock", first_count: int = 0):
        """Create an item plus a first (usable) status bucket."""
        item_id = self._db.exec_proc("usp_inventory_item_insert", {
            "name": to_param(name),
            "per_cell_qty": float(per_cell_qty or 0),
        }, returns_id=True)
        if item_id is not None and first_status:
            self._db.exec_proc("usp_inventory_status_insert", {
                "item_id": int(item_id),
                "name": to_param(first_status),
                "count": max(0, int(first_count)),
                "is_usable": 1,
            }, returns_id=True)
        self.reload()
        return item_id

    def update_item(self, item_id, name: str, per_cell_qty: float) -> None:
        self._db.exec_proc("usp_inventory_item_update", {
            "id": int(item_id),
            "name": to_param(name),
            "per_cell_qty": float(per_cell_qty or 0),
        })
        self.reload()

    def delete_item(self, item_id) -> None:
        self._db.exec_proc("usp_inventory_item_delete", {"id": int(item_id)})
        self.reload()

    # --------------------------------------------------------- Status writes
    def add_status(self, item_id, name: str, count: int = 0, is_usable: bool = True):
        sid = self._db.exec_proc("usp_inventory_status_insert", {
            "item_id": int(item_id),
            "name": to_param(name),
            "count": max(0, int(count)),
            "is_usable": 1 if is_usable else 0,
        }, returns_id=True)
        self.reload()
        return sid

    def update_status(self, status_id, name: str, is_usable: bool) -> None:
        self._db.exec_proc("usp_inventory_status_update", {
            "id": int(status_id),
            "name": to_param(name),
            "is_usable": 1 if is_usable else 0,
        })
        self.reload()

    def delete_status(self, status_id) -> None:
        self._db.exec_proc("usp_inventory_status_delete", {"id": int(status_id)})
        self.reload()

    def set_status_count(self, status_id, count: int) -> None:
        self._db.exec_proc("usp_inventory_status_set_count", {
            "id": int(status_id), "count": max(0, int(count))})
        self.reload()

    def adjust_status(self, status_id, delta: int) -> None:
        """Change a bucket count by ``delta`` (stepper); the proc clamps at 0."""
        self._db.exec_proc("usp_inventory_status_adjust", {
            "id": int(status_id), "delta": int(delta)})
        self.reload()

    # ------------------------------------------- Deduction (used by events)
    def deduct(self, status_id, qty: int) -> None:
        """Remove ``qty`` from a bucket (clamped at 0). No reload (batch caller)."""
        self._db.exec_proc("usp_inventory_status_adjust", {
            "id": int(status_id), "delta": -abs(int(qty))})

    def restore(self, status_id, qty: int) -> None:
        """Add ``qty`` back to a bucket. No reload (batch caller reloads once)."""
        self._db.exec_proc("usp_inventory_status_adjust", {
            "id": int(status_id), "delta": abs(int(qty))})
