"""Inventory tab: items, their status buckets and stock counts.

One card per item. Each card shows the item's roll-up (usable / total /
requirement / need-to-order) and a row per status bucket with a +/- stepper and a
manual count field. A global "Cells" control drives every requirement
(requirement = per_cell_qty * cells). All edits go through :class:`InventoryManager`.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QLineEdit,
    QScrollArea, QSpinBox, QCheckBox, QGraphicsDropShadowEffect, QSizePolicy,
    QDialog, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIntValidator

from src.gui.styles.tab_styles import TAB_STYLE
from src.gui.styles.dialog_styles import DIALOG_STYLE
from src.gui.widgets.confirm_dialog import ConfirmDialog

_CARD = (
    "QFrame#ItemCard { background:#FFFFFF; border:1px solid #DCE6EB;"
    " border-radius:8px; }"
)
_PRIMARY = (
    "QPushButton { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    " stop:0 #55BDBD, stop:1 #3FA3A3); color:#FFFFFF; border:none;"
    " border-radius:8px; padding:9px 18px; font-size:12px; font-weight:700;"
    " letter-spacing:0.3px; }"
    " QPushButton:hover { background:#3FA3A3; }"
)
_STEP_BTN = (
    "QPushButton { background:#E4F2F2; color:#1A5E5E; border:1px solid #8FCFCF;"
    " border-radius:6px; font-size:16px; font-weight:700; }"
    " QPushButton:hover { background:#CFE9E9; }"
    " QPushButton:pressed { background:#BADEDE; }"
)
_ICON_BTN = (
    "QPushButton { background:transparent; border:none; border-radius:6px;"
    " padding:2px 6px; font-size:13px; color:#5A6B72; }"
    " QPushButton:hover { background:#EDF2F4; color:#1F2A33; }"
)
class InventoryTab(QWidget):
    """Stock inventory: add/remove items and status buckets, adjust counts."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.init_ui()

    # ----------------------------------------------------------------- UI
    def init_ui(self):
        self.setObjectName("TabRoot")
        self.setStyleSheet(TAB_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(14)
        root.addWidget(self._build_header())
        root.addLayout(self._build_toolbar())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_host = QWidget()
        self._list = QVBoxLayout(self._list_host)
        self._list.setContentsMargins(2, 2, 2, 2)
        self._list.setSpacing(14)
        scroll.setWidget(self._list_host)
        self._scroll = scroll
        root.addWidget(scroll, 1)

        self._rebuild_list()

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("PageHeader")
        header.setFixedHeight(70)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(24, 16, 24, 16)
        title = QLabel("IC Inventory")
        title.setObjectName("PageTitle")
        lay.addWidget(title, 1)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(63, 163, 163, 90))
        header.setGraphicsEffect(shadow)
        return header

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)
        cells_lbl = QLabel("Requirements for")
        cells_lbl.setStyleSheet("color:#4A5A66; font-size:13px; font-weight:600;")
        self.cells_spin = QSpinBox()
        self.cells_spin.setRange(0, 100000)
        self.cells_spin.setValue(self.manager.get_cell_count())
        self.cells_spin.setFixedWidth(90)
        self.cells_spin.setStyleSheet(
            "QSpinBox { background:#FFFFFF; border:1px solid #C7D3DB;"
            " border-radius:6px; padding:5px 8px; font-size:13px; font-weight:600; }")
        self.cells_spin.editingFinished.connect(self._on_cells_changed)
        cells_unit = QLabel("cells")
        cells_unit.setStyleSheet("color:#4A5A66; font-size:13px;")
        bar.addWidget(cells_lbl)
        bar.addWidget(self.cells_spin)
        bar.addWidget(cells_unit)
        bar.addStretch(1)
        add_btn = QPushButton("+  Add item")
        add_btn.setStyleSheet(_PRIMARY)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._add_item)
        bar.addWidget(add_btn)
        return bar

    # ------------------------------------------------------------- Rebuild
    def reload(self) -> None:
        self.manager.reload()
        self.cells_spin.blockSignals(True)
        self.cells_spin.setValue(self.manager.get_cell_count())
        self.cells_spin.blockSignals(False)
        self._rebuild_list()

    def _rebuild_list(self) -> None:
        pos = self._scroll.verticalScrollBar().value()
        while self._list.count():
            item = self._list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        items = self.manager.get_items()
        if not items:
            empty = QLabel("No inventory items yet. Use \"Add item\" to create one.")
            empty.setStyleSheet("color:#8895A0; font-size:14px; padding:24px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list.addWidget(empty)
        for it in items:
            self._list.addWidget(self._build_item_card(it))
        self._list.addStretch(1)
        self._scroll.verticalScrollBar().setValue(pos)

    def _build_item_card(self, item: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("ItemCard")
        card.setStyleSheet(_CARD)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(18, 14, 18, 16)
        outer.setSpacing(10)

        # --- header: name + per-cell, roll-ups, order badge, actions ---
        head = QHBoxLayout()
        head.setSpacing(10)
        name = QLabel(item["name"])
        name.setStyleSheet("font-size:16px; font-weight:700; color:#1F2A33;")
        per_cell = QLabel(f"{self._num(item['per_cell_qty'])} / cell")
        per_cell.setStyleSheet("color:#7E9097; font-size:12px;")
        head.addWidget(name)
        head.addWidget(per_cell)
        head.addStretch(1)
        head.addWidget(self._stat("Usable", self._num(item["usable"])))
        head.addWidget(self._stat("Total", self._num(item["total"])))
        head.addWidget(self._stat("Need", self._num(item["requirement"])))
        head.addWidget(self._order_badge(item["need_to_order"]))

        edit = QPushButton("Edit")
        edit.setStyleSheet(_ICON_BTN)
        edit.setCursor(Qt.CursorShape.PointingHandCursor)
        edit.clicked.connect(lambda _=False, it=item: self._edit_item(it))
        remove = QPushButton("Delete")
        remove.setStyleSheet(_ICON_BTN)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(lambda _=False, it=item: self._delete_item(it))
        head.addWidget(edit)
        head.addWidget(remove)
        outer.addLayout(head)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color:#EAEFF2;")
        outer.addWidget(line)

        # --- one row per status bucket ---
        for s in item["statuses"]:
            outer.addWidget(self._status_row(item, s))

        add_status = QPushButton("+  Add status")
        add_status.setStyleSheet(
            "QPushButton { background:transparent; color:#2F7F7F; border:none;"
            " font-size:12px; font-weight:600; text-align:left; padding:2px 0; }"
            " QPushButton:hover { color:#1A5E5E; }")
        add_status.setCursor(Qt.CursorShape.PointingHandCursor)
        add_status.clicked.connect(lambda _=False, it=item: self._add_status(it))
        outer.addWidget(add_status, 0, Qt.AlignmentFlag.AlignLeft)
        return card

    def _status_row(self, item: dict, s: dict) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        name = QLabel(s["name"])
        name.setStyleSheet("font-size:13px; color:#33404A;")
        name.setMinimumWidth(180)
        name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(name)

        usable = QCheckBox("counts as usable")
        usable.setChecked(s["is_usable"])
        usable.setStyleSheet("QCheckBox { color:#6B7A85; font-size:11px; }")
        usable.toggled.connect(
            lambda on, sid=s["id"], nm=s["name"]: self._toggle_usable(sid, nm, on))
        lay.addWidget(usable)

        if s["id"] == item.get("default_status_id"):
            tag = QLabel("events use this")
            tag.setStyleSheet(
                "QLabel { background:#E4F2F2; color:#1A5E5E; border:1px solid #8FCFCF;"
                " border-radius:6px; padding:2px 8px; font-size:10px; font-weight:600; }")
            tag.setToolTip("Events deduct from the first usable bucket.")
            lay.addWidget(tag)

        lay.addWidget(self._stepper(s))

        remove = QPushButton("✕")
        remove.setStyleSheet(_ICON_BTN)
        remove.setFixedWidth(28)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setToolTip("Remove this status")
        remove.clicked.connect(
            lambda _=False, it=item, sid=s["id"]: self._delete_status(it, sid))
        lay.addWidget(remove)
        return row

    def _stepper(self, s: dict) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        minus = QPushButton("-")
        minus.setStyleSheet(_STEP_BTN)
        minus.setFixedSize(30, 30)
        minus.setCursor(Qt.CursorShape.PointingHandCursor)
        minus.clicked.connect(lambda _=False, sid=s["id"]: self._adjust(sid, -1))
        field = QLineEdit(str(s["count"]))
        field.setValidator(QIntValidator(0, 1000000, self))
        field.setFixedWidth(66)
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        field.setStyleSheet(
            "QLineEdit { background:#F7FAFC; border:1px solid #D8E2E8;"
            " border-radius:6px; padding:5px; font-size:14px; font-weight:600;"
            " color:#1F2A33; }")
        field.editingFinished.connect(
            lambda sid=s["id"], f=field: self._set_count(sid, f.text()))
        plus = QPushButton("+")
        plus.setStyleSheet(_STEP_BTN)
        plus.setFixedSize(30, 30)
        plus.setCursor(Qt.CursorShape.PointingHandCursor)
        plus.clicked.connect(lambda _=False, sid=s["id"]: self._adjust(sid, 1))
        lay.addWidget(minus)
        lay.addWidget(field)
        lay.addWidget(plus)
        return box

    # ------------------------------------------------------------- Widgets
    def _stat(self, label: str, value: str) -> QFrame:
        chip = QFrame()
        chip.setStyleSheet(
            "QFrame { background:#F0F6F6; border:1px solid #DBE9E9; border-radius:8px; }")
        lay = QVBoxLayout(chip)
        lay.setContentsMargins(12, 5, 12, 5)
        lay.setSpacing(0)
        v = QLabel(value)
        v.setStyleSheet("font-size:15px; font-weight:700; color:#256; border:none;"
                        " background:transparent;")
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        k = QLabel(label)
        k.setStyleSheet("font-size:10px; color:#7E9097; border:none;"
                        " background:transparent;")
        k.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(v)
        lay.addWidget(k)
        return chip

    def _order_badge(self, need: float) -> QLabel:
        badge = QLabel()
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if need > 0:
            badge.setText(f"Order {self._num(need)}")
            badge.setStyleSheet(
                "QLabel { background:#F5DAD6; color:#9A2A1E; border:1px solid #E7C6C1;"
                " border-radius:8px; padding:8px 12px; font-size:12px; font-weight:700; }")
        else:
            surplus = self._num(-need)
            badge.setText("Stocked" if need == 0 else f"Surplus {surplus}")
            badge.setStyleSheet(
                "QLabel { background:#D7EFDD; color:#1E6B3A; border:1px solid #BEE3C8;"
                " border-radius:8px; padding:8px 12px; font-size:12px; font-weight:700; }")
        return badge

    @staticmethod
    def _num(n) -> str:
        f = float(n)
        return str(int(f)) if f.is_integer() else f"{f:g}"

    # --------------------------------------------------------- Count edits
    def _adjust(self, status_id, delta: int) -> None:
        self.manager.adjust_status(status_id, delta)
        self._rebuild_list()

    def _set_count(self, status_id, text: str) -> None:
        try:
            value = int(text)
        except (ValueError, TypeError):
            return
        self.manager.set_status_count(status_id, value)
        self._rebuild_list()

    def _on_cells_changed(self) -> None:
        self.manager.set_cell_count(self.cells_spin.value())
        self._rebuild_list()

    # --------------------------------------------------------- Status edits
    def _toggle_usable(self, status_id, name, on: bool) -> None:
        self.manager.update_status(status_id, name, on)
        self._rebuild_list()

    def _add_status(self, item: dict) -> None:
        dlg = _StatusDialog(self, item_name=item["name"])
        dlg.exec()
        if dlg.saved:
            self.manager.add_status(item["id"], dlg.name, dlg.count, dlg.is_usable)
            self._rebuild_list()

    def _delete_status(self, item: dict, status_id) -> None:
        if len(item["statuses"]) <= 1:
            QMessageBox.information(
                self, "Cannot remove",
                "An item needs at least one status. Delete the item instead.")
            return
        s = next((x for x in item["statuses"] if x["id"] == status_id), None)
        if not ConfirmDialog.ask(
                self, title="Remove status",
                message=f"Remove <b>{(s or {}).get('name', '')}</b> from "
                        f"<b>{item['name']}</b>?",
                confirm_text="Remove", cancel_text="Cancel", destructive=True):
            return
        self.manager.delete_status(status_id)
        self._rebuild_list()

    # ----------------------------------------------------------- Item edits
    def _add_item(self) -> None:
        dlg = _ItemDialog(self)
        dlg.exec()
        if dlg.saved:
            self.manager.add_item(dlg.name, dlg.per_cell,
                                  first_status=dlg.first_status,
                                  first_count=dlg.first_count)
            self._rebuild_list()

    def _edit_item(self, item: dict) -> None:
        dlg = _ItemDialog(self, item=item)
        dlg.exec()
        if dlg.saved:
            self.manager.update_item(item["id"], dlg.name, dlg.per_cell)
            self._rebuild_list()

    def _delete_item(self, item: dict) -> None:
        if not ConfirmDialog.ask(
                self, title="Delete item",
                message=f"Delete <b>{item['name']}</b> and all its statuses?",
                confirm_text="Yes, delete", cancel_text="Cancel", destructive=True):
            return
        self.manager.delete_item(item["id"])
        self._rebuild_list()


class _ItemDialog(QDialog):
    """Add or edit an item: name + per-cell requirement (and, when adding, a first
    status bucket)."""

    def __init__(self, parent=None, item=None):
        super().__init__(parent)
        self.item = item
        self.adding = item is None
        self.saved = False
        self.name = ""
        self.per_cell = 0.0
        self.first_status = "In stock"
        self.first_count = 0
        self._build()

    def _build(self):
        self.setWindowTitle("Item")
        self.setModal(True)
        self.setStyleSheet(DIALOG_STYLE)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)

        title = QLabel(("Add" if self.adding else "Edit") + " item")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#1F6B6B;")
        lay.addWidget(title)

        self.name_edit = QLineEdit("" if self.adding else self.item["name"])
        self.name_edit.setPlaceholderText("Item name (e.g. Lids)")
        lay.addWidget(self._field("Name", self.name_edit))

        self.per_cell_edit = QLineEdit(
            "" if self.adding else _num_str(self.item["per_cell_qty"]))
        self.per_cell_edit.setValidator(_float_validator(self))
        self.per_cell_edit.setPlaceholderText("Units needed per cell (e.g. 6)")
        lay.addWidget(self._field("Per cell", self.per_cell_edit))

        if self.adding:
            self.status_edit = QLineEdit("In stock")
            lay.addWidget(self._field("First status", self.status_edit))
            self.count_edit = QLineEdit("0")
            self.count_edit.setValidator(QIntValidator(0, 1000000, self))
            lay.addWidget(self._field("Count", self.count_edit))

        lay.addStretch(1)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        cancel.setAutoDefault(False)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        lay.addLayout(buttons)

    def _field(self, label, widget) -> QWidget:
        row = QWidget()
        r = QHBoxLayout(row)
        r.setContentsMargins(0, 0, 0, 0)
        r.setSpacing(12)
        lab = QLabel(label)
        lab.setObjectName("FieldLabel")
        lab.setFixedWidth(96)
        r.addWidget(lab)
        r.addWidget(widget, 1)
        return row

    def _on_save(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Name required", "Please enter an item name.")
            return
        try:
            per_cell = float((self.per_cell_edit.text() or "0").replace(",", "."))
        except ValueError:
            QMessageBox.warning(self, "Invalid number",
                                "Per cell must be a number.")
            return
        self.name = name
        self.per_cell = per_cell
        if self.adding:
            self.first_status = self.status_edit.text().strip() or "In stock"
            try:
                self.first_count = int(self.count_edit.text() or "0")
            except ValueError:
                self.first_count = 0
        self.saved = True
        self.accept()


class _StatusDialog(QDialog):
    """Add a status bucket to an item."""

    def __init__(self, parent=None, item_name=""):
        super().__init__(parent)
        self.saved = False
        self.name = ""
        self.count = 0
        self.is_usable = True
        self._item_name = item_name
        self._build()

    def _build(self):
        self.setWindowTitle("Status")
        self.setModal(True)
        self.setStyleSheet(DIALOG_STYLE)
        self.setMinimumWidth(400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        title = QLabel(f"Add status to {self._item_name}")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#1F6B6B;")
        lay.addWidget(title)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Status name (e.g. Good ones, Damaged)")
        lay.addWidget(self._field("Name", self.name_edit))
        self.count_edit = QLineEdit("0")
        self.count_edit.setValidator(QIntValidator(0, 1000000, self))
        lay.addWidget(self._field("Count", self.count_edit))
        self.usable_chk = QCheckBox("counts as usable stock")
        self.usable_chk.setChecked(True)
        lay.addWidget(self.usable_chk)

        lay.addStretch(1)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        lay.addLayout(buttons)

    def _field(self, label, widget) -> QWidget:
        row = QWidget()
        r = QHBoxLayout(row)
        r.setContentsMargins(0, 0, 0, 0)
        r.setSpacing(12)
        lab = QLabel(label)
        lab.setObjectName("FieldLabel")
        lab.setFixedWidth(96)
        r.addWidget(lab)
        r.addWidget(widget, 1)
        return row

    def _on_save(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Name required", "Please enter a status name.")
            return
        self.name = name
        try:
            self.count = int(self.count_edit.text() or "0")
        except ValueError:
            self.count = 0
        self.is_usable = self.usable_chk.isChecked()
        self.saved = True
        self.accept()


def _num_str(n) -> str:
    f = float(n)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def _float_validator(parent):
    from PyQt6.QtGui import QRegularExpressionValidator
    from PyQt6.QtCore import QRegularExpression
    return QRegularExpressionValidator(QRegularExpression(r"^\d*[.,]?\d*$"), parent)
