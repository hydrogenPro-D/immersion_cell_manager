"""Event Log tab: log occurrences of events that consume inventory.

The log table lists past events (newest first). "Log event" opens a dialog that
shows the chosen event's inventory cost against current stock, warns (and asks to
continue) when stock is short, then deducts on save. "Manage event types" defines
the reusable events and their default cost recipe.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QLineEdit,
    QTextEdit, QComboBox, QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QDialog, QScrollArea, QGraphicsDropShadowEffect, QMessageBox,
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor

from src.gui.styles.tab_styles import TAB_STYLE
from src.gui.styles.dialog_styles import DIALOG_STYLE
from src.gui.widgets.confirm_dialog import ConfirmDialog
from src.gui.widgets.edit_row_dialog import CalendarDateEdit

_PRIMARY = (
    "QPushButton { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    " stop:0 #55BDBD, stop:1 #3FA3A3); color:#FFFFFF; border:none;"
    " border-radius:8px; padding:9px 18px; font-size:12px; font-weight:700;"
    " letter-spacing:0.3px; }"
    " QPushButton:hover { background:#3FA3A3; }"
)
_SECONDARY = (
    "QPushButton { background:#EBEFF2; color:#33404A; border:none;"
    " border-radius:8px; padding:9px 18px; font-size:12px; font-weight:600; }"
    " QPushButton:hover { background:#DCE3E8; }"
)
_DELETE_BTN = (
    "QPushButton { background:#F5DAD6; color:#9A2A1E; border:1px solid #E7C6C1;"
    " border-radius:8px; padding:8px 16px; font-weight:600; }"
    " QPushButton:hover { background:#E9C4C0; }"
)
_TABLE = (
    "QTableWidget { background:#FFFFFF; border:1px solid #E1E8ED;"
    " border-radius:8px; gridline-color:#EEF2F5; }"
    "QHeaderView::section { background:#E2EAEF; color:#4A5A66;"
    " padding:6px 8px; border:none; font-weight:600; }"
)


class EventLogTab(QWidget):
    """History of logged events + entry points to log and to manage event types."""

    def __init__(self, manager, on_inventory_changed=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        # Called after an event changes inventory, so the Inventory tab refreshes.
        self.on_inventory_changed = on_inventory_changed
        self.init_ui()

    # ----------------------------------------------------------------- UI
    def init_ui(self):
        self.setObjectName("TabRoot")
        self.setStyleSheet(TAB_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(14)
        root.addWidget(self._build_header())

        bar = QHBoxLayout()
        bar.setSpacing(10)
        manage = QPushButton("Manage event types")
        manage.setStyleSheet(_SECONDARY)
        manage.setCursor(Qt.CursorShape.PointingHandCursor)
        manage.clicked.connect(self._manage_types)
        bar.addWidget(manage)
        bar.addStretch(1)
        log_btn = QPushButton("+  Log event")
        log_btn.setStyleSheet(_PRIMARY)
        log_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        log_btn.clicked.connect(self._log_event)
        bar.addWidget(log_btn)
        root.addLayout(bar)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(_TABLE)
        self.table.doubleClicked.connect(
            lambda idx: self._edit_log(idx.row()))
        headers = ["Event", "Event date", "Logged", "Person", "Cost", "Comment"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        root.addWidget(self.table, 1)

        self._refresh_table()

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("PageHeader")
        header.setFixedHeight(70)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(24, 16, 24, 16)
        title = QLabel("Event Log")
        title.setObjectName("PageTitle")
        lay.addWidget(title, 1)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(63, 163, 163, 90))
        header.setGraphicsEffect(shadow)
        return header

    # ------------------------------------------------------------- Table
    def reload(self) -> None:
        self.manager.reload()
        self._refresh_table()

    def _refresh_table(self) -> None:
        logs = self.manager.get_logs()
        self.table.setRowCount(len(logs))
        for r, lg in enumerate(logs):
            cost = ", ".join(f"{c['qty']} {c['item_name']}" for c in lg["costs"]) \
                or "no cost"
            values = [lg["event_name"], lg["event_date"], lg["logged_at"][:16],
                      lg["person"], cost, lg["comment"]]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, item)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.resizeColumnsToContents()
        header.setStretchLastSection(True)
        self.table.resizeRowsToContents()

    def _notify_inventory(self) -> None:
        if self.on_inventory_changed:
            self.on_inventory_changed()

    # --------------------------------------------------------- Log actions
    def _log_event(self) -> None:
        if not self.manager.get_types():
            QMessageBox.information(
                self, "No events yet",
                "Create an event type first (Manage event types).")
            return
        dlg = LogEventDialog(self, self.manager)
        dlg.exec()
        if dlg.saved:
            self._refresh_table()
            self._notify_inventory()

    def _edit_log(self, row: int) -> None:
        logs = self.manager.get_logs()
        if not (0 <= row < len(logs)):
            return
        dlg = LogEventDialog(self, self.manager, log=logs[row])
        dlg.exec()
        if dlg.saved or dlg.deleted:
            self._refresh_table()
            self._notify_inventory()

    def _manage_types(self) -> None:
        dlg = ManageEventTypesDialog(self, self.manager)
        dlg.exec()
        self._refresh_table()


class LogEventDialog(QDialog):
    """Log a new event, or edit an existing log entry (including its costs)."""

    def __init__(self, parent, manager, log=None):
        super().__init__(parent)
        self.manager = manager
        self.log = log
        self.editing = log is not None
        self.saved = False
        self.deleted = False
        self._rows = []  # per cost line: dict(line, spin, after_lbl, base, widget)
        self._build()

    def _build(self):
        self.setWindowTitle("Log event")
        self.setModal(True)
        self.resize(560, 640)
        self.setMinimumSize(460, 480)
        self.setStyleSheet(DIALOG_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("Edit logged event" if self.editing else "Log an event")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#1F6B6B;")
        root.addWidget(title)

        # Event type: a dropdown when logging, fixed label when editing.
        if self.editing:
            row = self._field_row("Event")
            lbl = QLabel(self.log["event_name"])
            lbl.setStyleSheet("font-size:14px; font-weight:600; color:#1F2A33;")
            row.addWidget(lbl, 1)
        else:
            row = self._field_row("Event")
            self.type_combo = QComboBox()
            self.type_combo.setObjectName("ChoiceField")
            for t in self.manager.get_types():
                self.type_combo.addItem(t["name"], t["id"])
            self.type_combo.currentIndexChanged.connect(self._on_type_changed)
            row.addWidget(self.type_combo, 1)

        # Cost preview.
        cost_label = QLabel("Inventory cost")
        cost_label.setStyleSheet(
            "font-size:11px; font-weight:600; letter-spacing:0.6px; color:#4A5A66;")
        root.addWidget(cost_label)
        self._cost_host = QWidget()
        self._cost_layout = QVBoxLayout(self._cost_host)
        self._cost_layout.setContentsMargins(0, 0, 0, 0)
        self._cost_layout.setSpacing(6)
        cost_scroll = QScrollArea()
        cost_scroll.setWidgetResizable(True)
        cost_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        cost_scroll.setStyleSheet(
            "QScrollArea { border:1px solid #E1E8ED; border-radius:8px;"
            " background:#FAFCFD; }")
        cost_scroll.setWidget(self._cost_host)
        cost_scroll.setMinimumHeight(140)
        root.addWidget(cost_scroll, 1)

        # Person / comment / dates.
        prow = self._field_row("Person")
        self.person_edit = QLineEdit(self.log["person"] if self.editing else "")
        self.person_edit.setPlaceholderText("Who logged this")
        prow.addWidget(self.person_edit, 1)

        crow = self._field_row("Comment")
        self.comment_edit = QTextEdit(self.log["comment"] if self.editing else "")
        self.comment_edit.setObjectName("CommentsField")
        self.comment_edit.setMinimumHeight(60)
        self.comment_edit.setTabChangesFocus(True)
        crow.addWidget(self.comment_edit, 1)

        drow = self._field_row("Event date")
        self.date_edit = CalendarDateEdit()
        self.date_edit.setObjectName("DateField")
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        if self.editing and self.log["event_date"]:
            self.date_edit.setDate(QDate.fromString(self.log["event_date"][:10],
                                                    "yyyy-MM-dd"))
        else:
            self.date_edit.setDate(QDate.currentDate())
        drow.addWidget(self.date_edit, 1)

        lrow = self._field_row("Logged")
        logged = (self.log["logged_at"][:16] if self.editing else "now, on save")
        logged_lbl = QLabel(logged)
        logged_lbl.setStyleSheet("color:#7E9097; font-size:13px;")
        lrow.addWidget(logged_lbl, 1)

        # Buttons.
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        if self.editing:
            delete = QPushButton("Delete")
            delete.setStyleSheet(_DELETE_BTN)
            delete.setAutoDefault(False)
            delete.clicked.connect(self._on_delete)
            buttons.addWidget(delete)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(_SECONDARY)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setStyleSheet(_PRIMARY)
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

        self._load_costs()

    def _field_row(self, label: str) -> QHBoxLayout:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        lab = QLabel(label)
        lab.setObjectName("FieldLabel")
        lab.setFixedWidth(90)
        lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        row.addWidget(lab, 0, Qt.AlignmentFlag.AlignTop)
        self.layout().addWidget(wrapper)
        return row

    # ---------------------------------------------------------- Cost rows
    def _current_costs(self) -> list:
        if self.editing:
            return self.manager.resolve_costs(self.log["costs"])
        tid = self.type_combo.currentData()
        t = self.manager.get_type(tid)
        return self.manager.resolve_costs(t["costs"]) if t else []

    def _on_type_changed(self, *_a):
        self._load_costs()

    def _load_costs(self):
        while self._cost_layout.count():
            it = self._cost_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._rows = []
        lines = self._current_costs()
        if not lines:
            empty = QLabel("This event has no inventory cost.")
            empty.setStyleSheet("color:#8895A0; font-size:13px; padding:10px;")
            self._cost_layout.addWidget(empty)
            self._cost_layout.addStretch(1)
            return
        for line in lines:
            self._cost_layout.addWidget(self._cost_row(line))
        self._cost_layout.addStretch(1)

    def _cost_row(self, line: dict) -> QWidget:
        # When editing, stock already reflects this log's deduction, so the true
        # base availability is the current count plus what this log took.
        old_qty = line["qty"] if self.editing else 0
        base = line["available"] + old_qty

        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(10)

        name = QLabel(line["item_name"])
        name.setStyleSheet("font-size:13px; font-weight:600; color:#33404A;")
        name.setMinimumWidth(120)
        bucket = QLabel(f"from {line['status_name']}" if line["status_name"] else "")
        bucket.setStyleSheet("color:#7E9097; font-size:11px;")

        spin = QSpinBox()
        spin.setRange(0, 1000000)
        spin.setValue(line["qty"])
        spin.setFixedWidth(72)
        after = QLabel()
        after.setStyleSheet("font-size:12px;")

        def recompute(v=None):
            qty = spin.value()
            left = base - qty
            after.setText(f"{max(left, 0)} left of {base}")
            after.setStyleSheet(
                "font-size:12px; color:%s;" % ("#9A2A1E" if qty > base else "#5A6B72"))
        spin.valueChanged.connect(recompute)
        recompute()

        lay.addWidget(name)
        lay.addWidget(bucket)
        lay.addStretch(1)
        lay.addWidget(QLabel("qty"))
        lay.addWidget(spin)
        lay.addWidget(after)

        self._rows.append({"line": line, "spin": spin, "base": base})
        return row

    def _collect_lines(self) -> list:
        lines = []
        for r in self._rows:
            line = dict(r["line"])
            line["qty"] = r["spin"].value()
            lines.append(line)
        return lines

    # ----------------------------------------------------------- Save/Del
    def _on_save(self):
        lines = self._collect_lines()
        short = [r for r in self._rows if r["spin"].value() > r["base"]]
        if short:
            names = ", ".join(f"{r['spin'].value()} {r['line']['item_name']} "
                              f"(have {r['base']})" for r in short)
            if not ConfirmDialog.ask(
                    self, title="Not enough in stock",
                    message="Some items are short: " + names + ".",
                    informative="Log it anyway? The stock will be set to 0 for "
                                "those buckets.",
                    confirm_text="Log anyway", cancel_text="Cancel",
                    destructive=True):
                return
        person = self.person_edit.text().strip()
        comment = self.comment_edit.toPlainText().strip()
        event_date = self.date_edit.date().toString("yyyy-MM-dd")
        if self.editing:
            self.manager.update_log(self.log["id"], person, comment, event_date,
                                    cost_lines=lines)
        else:
            tid = self.type_combo.currentData()
            tname = self.manager.get_type(tid)["name"]
            self.manager.log_event(tid, tname, person, comment, event_date, lines)
        self.saved = True
        self.accept()

    def _on_delete(self):
        restore = ConfirmDialog.ask(
            self, title="Delete logged event",
            message="Delete this logged event?",
            informative="Add the items it consumed back to inventory?",
            confirm_text="Delete and restore", cancel_text="Delete only")
        # ConfirmDialog is yes/no; "yes" = restore, "no" = delete only. Either way
        # we delete; a separate cancel is offered by closing the dialog. To keep a
        # true cancel, ask again only if needed.
        self.manager.delete_log(self.log["id"], restore=restore)
        self.deleted = True
        self.accept()


class ManageEventTypesDialog(QDialog):
    """List of event types with add / edit / delete."""

    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._build()

    def _build(self):
        self.setWindowTitle("Event types")
        self.setModal(True)
        self.resize(560, 520)
        self.setMinimumSize(440, 380)
        self.setStyleSheet(DIALOG_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("Event types")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#1F6B6B;")
        head.addWidget(title)
        head.addStretch(1)
        add = QPushButton("+  New event")
        add.setStyleSheet(_PRIMARY)
        add.clicked.connect(self._add)
        head.addWidget(add)
        root.addLayout(head)

        self.list = QTableWidget()
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setShowGrid(False)
        self.list.verticalHeader().setVisible(False)
        self.list.setStyleSheet(_TABLE)
        self.list.setColumnCount(2)
        self.list.setHorizontalHeaderLabels(["Event", "Inventory cost"])
        self.list.doubleClicked.connect(lambda idx: self._edit(idx.row()))
        root.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        edit = QPushButton("Edit")
        edit.setStyleSheet(_SECONDARY)
        edit.clicked.connect(lambda: self._edit(self.list.currentRow()))
        delete = QPushButton("Delete")
        delete.setStyleSheet(_DELETE_BTN)
        delete.clicked.connect(lambda: self._delete(self.list.currentRow()))
        buttons.addWidget(edit)
        buttons.addWidget(delete)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.setStyleSheet(_SECONDARY)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self._refresh()

    def _refresh(self):
        types = self.manager.get_types(include_archived=True)
        self._types = types
        self.list.setRowCount(len(types))
        for r, t in enumerate(types):
            cost = ", ".join(
                f"{c['qty']} {(self.manager.inventory.get_item(c['item_id']) or {}).get('name', '?')}"
                for c in t["costs"]) or "no cost"
            name = t["name"] + ("  (archived)" if t["is_archived"] else "")
            self.list.setItem(r, 0, QTableWidgetItem(name))
            self.list.setItem(r, 1, QTableWidgetItem(cost))
        self.list.resizeColumnsToContents()
        self.list.horizontalHeader().setStretchLastSection(True)

    def _add(self):
        dlg = EventTypeDialog(self, self.manager)
        dlg.exec()
        if dlg.saved:
            self._refresh()

    def _edit(self, row):
        if not (0 <= row < len(self._types)):
            return
        dlg = EventTypeDialog(self, self.manager, event_type=self._types[row])
        dlg.exec()
        if dlg.saved:
            self._refresh()

    def _delete(self, row):
        if not (0 <= row < len(self._types)):
            return
        t = self._types[row]
        if not ConfirmDialog.ask(
                self, title="Delete event type",
                message=f"Delete the event <b>{t['name']}</b>?",
                informative="Past logs of this event are kept.",
                confirm_text="Delete", cancel_text="Cancel", destructive=True):
            return
        self.manager.delete_type(t["id"])
        self._refresh()


class EventTypeDialog(QDialog):
    """Create or edit an event type and its default cost recipe."""

    def __init__(self, parent, manager, event_type=None):
        super().__init__(parent)
        self.manager = manager
        self.event_type = event_type
        self.editing = event_type is not None
        self.saved = False
        self._cost_rows = []  # dict(combo, spin)
        self._build()

    def _build(self):
        self.setWindowTitle("Event type")
        self.setModal(True)
        self.resize(520, 560)
        self.setMinimumSize(420, 420)
        self.setStyleSheet(DIALOG_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("Edit event" if self.editing else "New event")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#1F6B6B;")
        root.addWidget(title)

        self.name_edit = QLineEdit(self.event_type["name"] if self.editing else "")
        self.name_edit.setPlaceholderText("Event name")
        root.addWidget(self._labeled("Name", self.name_edit))

        self.desc_edit = QTextEdit(
            self.event_type["description"] if self.editing else "")
        self.desc_edit.setObjectName("CommentsField")
        self.desc_edit.setMinimumHeight(56)
        self.desc_edit.setTabChangesFocus(True)
        root.addWidget(self._labeled("Description", self.desc_edit))

        cost_lbl = QLabel("Inventory needs")
        cost_lbl.setStyleSheet(
            "font-size:11px; font-weight:600; letter-spacing:0.6px; color:#4A5A66;")
        root.addWidget(cost_lbl)
        self._cost_host = QWidget()
        self._cost_layout = QVBoxLayout(self._cost_host)
        self._cost_layout.setContentsMargins(0, 0, 0, 0)
        self._cost_layout.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.StyledPanel)
        scroll.setStyleSheet("QScrollArea { border:1px solid #E1E8ED;"
                             " border-radius:8px; background:#FAFCFD; }")
        scroll.setWidget(self._cost_host)
        root.addWidget(scroll, 1)

        add_line = QPushButton("+  Add item cost")
        add_line.setStyleSheet(
            "QPushButton { background:transparent; color:#2F7F7F; border:none;"
            " font-size:12px; font-weight:600; text-align:left; }"
            " QPushButton:hover { color:#1A5E5E; }")
        add_line.clicked.connect(lambda: self._add_cost_row())
        root.addWidget(add_line, 0, Qt.AlignmentFlag.AlignLeft)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(_SECONDARY)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setStyleSheet(_PRIMARY)
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

        if self.editing:
            for c in self.event_type["costs"]:
                self._add_cost_row(c["item_id"], c["qty"])

    def _labeled(self, label, widget) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        lab = QLabel(label)
        lab.setObjectName("FieldLabel")
        lab.setFixedWidth(96)
        lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        row.addWidget(lab, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(widget, 1)
        return wrapper

    def _add_cost_row(self, item_id=None, qty=1):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(10)
        combo = QComboBox()
        combo.setObjectName("ChoiceField")
        for it in self.manager.inventory.get_items():
            combo.addItem(it["name"], it["id"])
        if item_id is not None:
            idx = combo.findData(item_id)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        spin = QSpinBox()
        spin.setRange(1, 1000000)
        spin.setValue(max(1, int(qty)))
        spin.setFixedWidth(78)
        remove = QPushButton("✕")
        remove.setFixedWidth(28)
        remove.setStyleSheet(
            "QPushButton { background:transparent; border:none; color:#8895A0; }"
            " QPushButton:hover { color:#9A2A1E; }")
        entry = {"combo": combo, "spin": spin, "widget": row}
        remove.clicked.connect(lambda: self._remove_cost_row(entry))
        lay.addWidget(combo, 1)
        lay.addWidget(QLabel("qty"))
        lay.addWidget(spin)
        lay.addWidget(remove)
        self._cost_rows.append(entry)
        self._cost_layout.addWidget(row)

    def _remove_cost_row(self, entry):
        entry["widget"].deleteLater()
        self._cost_rows = [e for e in self._cost_rows if e is not entry]

    def _on_save(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Name required", "Please enter an event name.")
            return
        description = self.desc_edit.toPlainText().strip()
        # New recipe: {item_id: qty}, last row wins on duplicates.
        new_costs = {}
        for e in self._cost_rows:
            iid = e["combo"].currentData()
            if iid is not None:
                new_costs[iid] = e["spin"].value()

        if self.editing:
            type_id = self.event_type["id"]
            self.manager.update_type(type_id, name, description,
                                     self.event_type["is_archived"])
            old_ids = {c["item_id"] for c in self.event_type["costs"]}
        else:
            type_id = self.manager.add_type(name, description)
            old_ids = set()

        for item_id, qty in new_costs.items():
            self.manager.set_type_cost(type_id, item_id, qty)
        for item_id in old_ids - set(new_costs):  # removed lines
            self.manager.set_type_cost(type_id, item_id, 0)

        self.saved = True
        self.accept()
