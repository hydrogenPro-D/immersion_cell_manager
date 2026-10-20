"""Manager for the Inventory tab.

Backed by the database: reads ``icm.inventory_item`` / ``icm.inventory_config``
via SELECT and writes through the ``usp_inventory_*`` procs (migrations 018 +
019). Each item has one stock quantity. Derived numbers are computed live here,
like the source Excel:

    requirement   = per_cell_qty * cell_count
    need_to_order = requirement - quantity
"""

from src.data.db import get_db, DatabaseError, to_param


class InventoryManager:
    """Reads and edits the inventory items, their quantities and the config."""

    def __init__(self, db=None):
        self._db = db or get_db()
        self._items = []
        self._cell_count = 70
        self.reload()

    # ------------------------------------------------------------------ IO
    def reload(self) -> None:
        """(Re)load config + items from the database."""
        try:
            row = self._db.fetch_row(
                "SELECT cell_count FROM icm.inventory_config WHERE id = 1")
            self._cell_count = int(row["cell_count"]) if row else 70
        except DatabaseError:
            self._cell_count = 70

        try:
            items = self._db.fetch_all(
                "SELECT id, name, per_cell_qty, quantity"
                " FROM icm.inventory_item ORDER BY id")
        except DatabaseError:
            items = []  # tables not created / migrated yet
        self._items = [self._item_row(it) for it in items]

    def _item_row(self, it: dict) -> dict:
        per_cell = float(it["per_cell_qty"] or 0)
        quantity = int(it["quantity"] or 0)
        requirement = per_cell * self._cell_count
        return {
            "id": it["id"],
            "name": it["name"] or "",
            "per_cell_qty": per_cell,
            "quantity": quantity,
            "requirement": requirement,
            "need_to_order": requirement - quantity,
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
        # Only the derived numbers change: recompute them, no re-read.
        self._cell_count = int(cell_count)
        self._items = [self._item_row(it) for it in self._items]

    # ----------------------------------------------------------- Item writes
    def add_item(self, name: str, per_cell_qty: float, quantity: int = 0):
        item_id = self._db.exec_proc("usp_inventory_item_insert", {
            "name": to_param(name),
            "per_cell_qty": float(per_cell_qty or 0),
            "quantity": max(0, int(quantity)),
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

    # ------------------------------------------------------ Quantity writes
    def set_quantity(self, item_id, quantity: int):
        """Returns the item as stored now (None if it was deleted)."""
        self._db.exec_proc("usp_inventory_item_set_quantity", {
            "id": int(item_id), "quantity": max(0, int(quantity))})
        return self._reload_item(item_id)

    def adjust_quantity(self, item_id, delta: int):
        """Change the quantity by ``delta``; the proc clamps at 0. Returns the
        item as stored now (None if it was deleted)."""
        self._db.exec_proc("usp_inventory_item_adjust", {
            "id": int(item_id), "delta": int(delta)})
        return self._reload_item(item_id)

    def _reload_item(self, item_id):
        row = self._db.fetch_row(
            "SELECT id, name, per_cell_qty, quantity FROM icm.inventory_item WHERE id = ?",
            (int(item_id),))
        item = self._item_row(row) if row else None
        self._items = [item if it["id"] == item_id else it
                       for it in self._items if row or it["id"] != item_id]
        return item
