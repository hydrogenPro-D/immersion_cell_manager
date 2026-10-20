"""Inventory tab: items and how many of each are in stock.

One compact row card per item: name, an In stock stepper, and Need (still to
order = requirement - in stock, red while short). A global "Cells"
control drives every requirement (requirement = per_cell_qty * cells). All edits
go through :class:`InventoryManager`.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QLineEdit,
    QScrollArea, QSpinBox, QGraphicsDropShadowEffect, QDialog, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIntValidator

from src.gui.styles.tab_styles import TAB_STYLE
from src.gui.styles.dialog_styles import DIALOG_STYLE
from src.gui.widgets.confirm_dialog import ConfirmDialog

_CARD = (
    "QFrame#ItemCard { background:#FFFFFF; border:1px solid #DCE6EB;"
    " border-radius:0px; }"
)
_PRIMARY = (
    "QPushButton { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    " stop:0 #55BDBD, stop:1 #3FA3A3); color:#FFFFFF; border:none;"
    " border-radius:3px; padding:9px 18px; font-size:12px; font-weight:700;"
    " letter-spacing:0.3px; }"
    " QPushButton:hover { background:#3FA3A3; }"
)
_STEP_BTN = (
    "QPushButton { background:#E4F2F2; color:#1A5E5E; border:1px solid #8FCFCF;"
    " border-radius:2px; font-size:14px; font-weight:700; padding:0px; }"
    " QPushButton:hover { background:#CFE9E9; }"
    " QPushButton:pressed { background:#BADEDE; }"
)
_ICON_BTN = (
    "QPushButton { background:transparent; border:none; border-radius:2px;"
    " padding:2px 6px; font-size:13px; color:#000000; }"
    " QPushButton:hover { background:#EDF2F4; }"
)
# Number pills: (background, text, border) per kind.
_PILL = {
    "short": ("#FDE2E0", "#B42318", "#F5C2BD"),
    "ok":    ("#DCF3E3", "#1E6B3A", "#BEE3C8"),
}


class InventoryTab(QWidget):
    """Stock inventory: add/remove items, adjust their counts."""

    def __init__(self, manager, on_items_changed=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        # Called after items are added / renamed / deleted (event recipes use them).
        self.on_items_changed = on_items_changed
        self._cards = {}       # item id -> {"field", "pill", "of"}
        self._signature = None  # (id, name, per cell) per card, to spot a needed rebuild
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
        self._list.setSpacing(6)
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
        # Styled spin boxes lose their arrow icons; it's a typed field instead.
        self.cells_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.cells_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cells_spin.setStyleSheet(
            "QSpinBox { background:#FFFFFF; border:1px solid #C7D3DB;"
            " border-radius:2px; padding:5px 8px; font-size:13px; font-weight:600; }")
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
        self.refresh()

    def refresh(self) -> None:
        """Show the manager's current data; cards are updated in place unless
        items were added, removed or renamed."""
        if not self.cells_spin.hasFocus():
            self.cells_spin.blockSignals(True)
            self.cells_spin.setValue(self.manager.get_cell_count())
            self.cells_spin.blockSignals(False)
        items = self.manager.get_items()
        if self._item_signature(items) != self._signature:
            self._rebuild_list()
            return
        for it in items:
            self._update_card(it)

    @staticmethod
    def _item_signature(items) -> tuple:
        return tuple((it["id"], it["name"], it["per_cell_qty"]) for it in items)

    def _update_card(self, item: dict) -> None:
        refs = self._cards.get(item["id"])
        if refs is None:
            return
        if not refs["field"].hasFocus():  # don't overwrite what is being typed
            refs["field"].setText(str(item["quantity"]))
        to_order = max(item["need_to_order"], 0)
        refs["pill"].setText(self._num(to_order))
        self._style_pill(refs["pill"], "short" if to_order > 0 else "ok")
        refs["of"].setText(f"of {self._num(item['requirement'])}")

    def _rebuild_list(self) -> None:
        pos = self._scroll.verticalScrollBar().value()
        while self._list.count():
            item = self._list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        items = self.manager.get_items()
        self._cards = {}
        self._signature = self._item_signature(items)
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
        """One compact row: name | In stock | Need | actions."""
        refs = self._cards[item["id"]] = {}
        card = QFrame()
        card.setObjectName("ItemCard")
        card.setStyleSheet(_CARD)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(18, 5, 14, 5)
        lay.setSpacing(18)

        name = QLabel(item["name"])
        name.setStyleSheet("font-size:14px; font-weight:700; color:#000000;")
        per_cell = QLabel(f"{self._num(item['per_cell_qty'])} / cell")
        per_cell.setStyleSheet("font-size:12px; color:#000000;")
        lay.addWidget(name)
        lay.addWidget(per_cell)
        lay.addStretch(1)

        # Fixed column widths keep the columns aligned from card to card.
        lay.addWidget(self._column(
            "In stock", self._stepper(item["id"], item["quantity"], refs), 175))

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet("color:#DCE6EB;")
        lay.addWidget(divider)

        to_order = max(item["need_to_order"], 0)
        need = QWidget()
        need_lay = QHBoxLayout(need)
        need_lay.setContentsMargins(0, 0, 0, 0)
        need_lay.setSpacing(6)
        refs["pill"] = self._pill(self._num(to_order), "short" if to_order > 0 else "ok")
        need_lay.addWidget(refs["pill"])
        of = refs["of"] = QLabel(f"of {self._num(item['requirement'])}")
        of.setStyleSheet("font-size:12px; color:#000000;")
        need_lay.addWidget(of)
        need_lay.addStretch(1)
        need.setToolTip("Still to order: requirement minus what is in stock.")
        lay.addWidget(self._column("Need", need, 160))

        edit = QPushButton("Edit")
        edit.setStyleSheet(_ICON_BTN)
        edit.setCursor(Qt.CursorShape.PointingHandCursor)
        edit.clicked.connect(lambda _=False, it=item: self._edit_item(it))
        remove = QPushButton("Delete")
        remove.setStyleSheet(_ICON_BTN)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(lambda _=False, it=item: self._delete_item(it))
        lay.addWidget(edit)
        lay.addWidget(remove)
        return card

    def _stepper(self, item_id, count: int, refs: dict) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        minus = QPushButton("-")
        minus.setStyleSheet(_STEP_BTN)
        minus.setFixedSize(24, 24)
        minus.setCursor(Qt.CursorShape.PointingHandCursor)
        minus.clicked.connect(lambda _=False: self._adjust(item_id, -1))
        field = refs["field"] = QLineEdit(str(count))
        field.setValidator(QIntValidator(0, 1000000, self))
        field.setFixedSize(52, 24)
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        field.setStyleSheet(
            "QLineEdit { background:#FFFFFF; border:1px solid #D8E2E8;"
            " border-radius:2px; padding:0px 2px; font-size:13px; font-weight:600;"
            " color:#000000; }")
        field.editingFinished.connect(
            lambda f=field: self._set_quantity(item_id, f.text()))
        plus = QPushButton("+")
        plus.setStyleSheet(_STEP_BTN)
        plus.setFixedSize(24, 24)
        plus.setCursor(Qt.CursorShape.PointingHandCursor)
        plus.clicked.connect(lambda _=False: self._adjust(item_id, 1))
        lay.addWidget(minus)
        lay.addWidget(field)
        lay.addWidget(plus)
        lay.addStretch(1)
        return box

    # ------------------------------------------------------------- Widgets
    @staticmethod
    def _column(label: str, widget: QWidget, width: int) -> QWidget:
        """Small caption left of a value widget, at a fixed width (side by side
        keeps the rows short)."""
        col = QWidget()
        col.setFixedWidth(width)
        lay = QHBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        cap = QLabel(label)
        cap.setStyleSheet("font-size:11px; color:#000000;")
        lay.addWidget(cap)
        lay.addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        return col

    @classmethod
    def _pill(cls, text: str, kind: str) -> QLabel:
        pill = QLabel(text)
        pill.setFixedHeight(24)
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cls._style_pill(pill, kind)
        return pill

    @staticmethod
    def _style_pill(pill: QLabel, kind: str) -> None:
        if pill.property("kind") == kind:
            return  # restyling re-polishes the label; skip when unchanged
        pill.setProperty("kind", kind)
        bg, fg, border = _PILL[kind]
        pill.setStyleSheet(
            f"QLabel {{ background:{bg}; color:{fg}; border:1px solid {border};"
            " border-radius:2px; padding:0px 8px; font-size:12px; font-weight:700; }")

    @staticmethod
    def _num(n) -> str:
        f = float(n)
        return str(int(f)) if f.is_integer() else f"{f:g}"

    # --------------------------------------------------------- Count edits
    def _adjust(self, item_id, delta: int) -> None:
        self._show_item(item_id, self.manager.adjust_quantity(item_id, delta))

    def _set_quantity(self, item_id, text: str) -> None:
        try:
            value = int(text)
        except (ValueError, TypeError):
            return
        current = self.manager.get_item(item_id)
        if current is not None and current["quantity"] == value:
            return  # focus left the field without a change
        self._show_item(item_id, self.manager.set_quantity(item_id, value))

    def _show_item(self, item_id, item) -> None:
        if item is None:
            self._rebuild_list()  # deleted by another user meanwhile
        else:
            self._update_card(item)

    def _on_cells_changed(self) -> None:
        if self.cells_spin.value() == self.manager.get_cell_count():
            return
        self.manager.set_cell_count(self.cells_spin.value())
        for it in self.manager.get_items():
            self._update_card(it)

    def _notify_items_changed(self) -> None:
        if self.on_items_changed:
            self.on_items_changed()

    # ----------------------------------------------------------- Item edits
    def _add_item(self) -> None:
        dlg = _ItemDialog(self)
        dlg.exec()
        if dlg.saved:
            self.manager.add_item(dlg.name, dlg.per_cell,
                                  quantity=dlg.quantity)
            self._rebuild_list()
            self._notify_items_changed()

    def _edit_item(self, item: dict) -> None:
        dlg = _ItemDialog(self, item=item)
        dlg.exec()
        if dlg.saved:
            self.manager.update_item(item["id"], dlg.name, dlg.per_cell)
            self._rebuild_list()
            self._notify_items_changed()

    def _delete_item(self, item: dict) -> None:
        if not ConfirmDialog.ask(
                self, title="Delete item",
                message=f"Delete <b>{item['name']}</b> and its stock counts?",
                confirm_text="Yes, delete", cancel_text="Cancel", destructive=True):
            return
        self.manager.delete_item(item["id"])
        self._rebuild_list()
        self._notify_items_changed()


# Same squared look as the Event Log dialogs.
_ITEM_DIALOG = DIALOG_STYLE + (
    "QLabel#FieldLabel { color:#000000; }"
    "QLineEdit { border-radius:2px; }"
    "QPushButton { border-radius:3px; }"
)


class _ItemDialog(QDialog):
    """Add or edit an item: name + per-cell requirement (and, when adding, the
    starting quantity)."""

    def __init__(self, parent=None, item=None):
        super().__init__(parent)
        self.item = item
        self.adding = item is None
        self.saved = False
        self.name = ""
        self.per_cell = 0.0
        self.quantity = 0
        self._build()

    def _build(self):
        self.setWindowTitle("Item")
        self.setModal(True)
        self.setStyleSheet(_ITEM_DIALOG)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)

        title = QLabel(("Add" if self.adding else "Edit") + " item")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#000000;")
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
            self.quantity_edit = QLineEdit("0")
            self.quantity_edit.setValidator(QIntValidator(0, 1000000, self))
            lay.addWidget(self._field("In stock", self.quantity_edit))

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
            self.quantity = int(self.quantity_edit.text() or "0")
        self.saved = True
        self.accept()


def _num_str(n) -> str:
    f = float(n)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def _float_validator(parent):
    from PyQt6.QtGui import QRegularExpressionValidator
    from PyQt6.QtCore import QRegularExpression
    return QRegularExpressionValidator(QRegularExpression(r"^\d*[.,]?\d*$"), parent)
