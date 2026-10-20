"""Event Log tab: log occurrences of events that consume inventory.

The log table lists past events (newest first). "Log event" opens a dialog that
shows the chosen event's inventory cost against current stock, warns (and asks to
continue) when stock is short, then deducts on save. "Manage event types" defines
the reusable events and their default cost recipe.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QLineEdit,
    QTextEdit, QComboBox, QSpinBox, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QDialog, QScrollArea, QGraphicsDropShadowEffect, QMessageBox,
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor

from src.data.db import DatabaseError
from src.gui.styles.tab_styles import TAB_STYLE
from src.gui.styles.dialog_styles import DIALOG_STYLE
from src.gui.widgets.confirm_dialog import ConfirmDialog
from src.gui.widgets.edit_row_dialog import CalendarDateEdit, ProjectComboBox
from src.gui.widgets.hover_border_table import (
    HoverBorderTable, HOVER_TABLE_STYLE, fit_columns,
)

_PRIMARY = (
    "QPushButton { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    " stop:0 #55BDBD, stop:1 #3FA3A3); color:#FFFFFF; border:none;"
    " border-radius:3px; padding:9px 18px; font-size:12px; font-weight:700;"
    " letter-spacing:0.3px; }"
    " QPushButton:hover { background:#3FA3A3; }"
)
_SECONDARY = (
    "QPushButton { background:#EBEFF2; color:#000000; border:none;"
    " border-radius:3px; padding:9px 18px; font-size:12px; font-weight:600; }"
    " QPushButton:hover { background:#DCE3E8; }"
)
_DELETE_BTN = (
    "QPushButton { background:#F5DAD6; color:#000000; border:1px solid #E7C6C1;"
    " border-radius:3px; padding:8px 16px; font-weight:600; }"
    " QPushButton:hover { background:#E9C4C0; }"
)

# Dialog look with black field labels and near-square inputs.
_DIALOG = DIALOG_STYLE + (
    "QLabel#FieldLabel { color:#000000; }"
    "QLineEdit, QTextEdit#CommentsField, QDateEdit#DateField { border-radius:2px; }"
)


# Log id stored on each row's first cell, so a sorted row still finds its log.
_LOG_ID = Qt.ItemDataRole.UserRole


def _dropdown() -> QComboBox:
    """Combo box with a visible ▾ arrow (reuses the Project field's look)."""
    combo = ProjectComboBox()
    combo.setObjectName("ProjectField")
    combo.setStyleSheet("QComboBox#ProjectField { border-radius:2px; }")
    combo.setCursor(Qt.CursorShape.PointingHandCursor)
    return combo


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
        bar.addSpacing(16)
        # Filters: "All" plus every event / person found in the log.
        self.event_filter = self._filter_combo()
        self.person_filter = self._filter_combo()
        for label, combo in (("Event", self.event_filter), ("Person", self.person_filter)):
            lab = QLabel(label)
            lab.setStyleSheet("font-size:13px; font-weight:600; color:#000000;")
            bar.addWidget(lab)
            bar.addWidget(combo)
        bar.addStretch(1)
        log_btn = QPushButton("+  Log event")
        log_btn.setStyleSheet(_PRIMARY)
        log_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        log_btn.clicked.connect(self._log_event)
        bar.addWidget(log_btn)
        root.addLayout(bar)

        # Same table look as the IC Logbook (teal header, row borders).
        self.table = HoverBorderTable(selectable=True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(HOVER_TABLE_STYLE)
        self.table.horizontalHeader().setFixedHeight(44)
        self.table.doubleClicked.connect(
            lambda idx: self._edit_log(idx.row()))
        headers = ["Event", "Event date", "Logged", "Person", "Cost", "Comment"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.enable_header_sort()
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

    def _filter_combo(self) -> QComboBox:
        combo = ProjectComboBox()  # combo with a visible ▾
        combo.setStyleSheet(
            "QComboBox { background:#FFFFFF; border:1px solid #C7D3DB; border-radius:2px;"
            " padding:5px 30px 5px 10px; min-width:150px; font-size:13px; color:#000000; }"
            " QComboBox::drop-down { width:0px; border:none; }"
            " QComboBox::down-arrow { image:none; }"
            " QComboBox QAbstractItemView { background:#FFFFFF; color:#000000;"
            " selection-background-color:#BFE6E6; selection-color:#000000; }")
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        combo.currentIndexChanged.connect(lambda _i: self._refresh_table())
        return combo

    def _fill_filters(self, logs: list) -> None:
        """Refill both filters from the log, keeping the current choices."""
        key = HoverBorderTable._sort_key  # same order as the column sort (case/accents ignored)
        events = sorted({lg["event_name"] for lg in logs if lg["event_name"]}, key=key)
        people = {}  # lower-case -> first spelling seen ("Csenger" / "csenger" are one)
        for lg in logs:
            name = lg["person"].strip()
            if name:
                people.setdefault(name.lower(), name)
        choices = (
            (self.event_filter, "All events", [(e, e) for e in events]),
            (self.person_filter, "All people",
             sorted(((v, k) for k, v in people.items()), key=lambda x: key(x[0]))),
        )
        for combo, all_text, items in choices:
            keep = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(all_text, None)
            for text, data in items:
                combo.addItem(text, data)
            index = combo.findData(keep) if keep is not None else 0
            combo.setCurrentIndex(max(index, 0))
            combo.blockSignals(False)

    def _refresh_table(self) -> None:
        all_logs = self.manager.get_logs()
        self._fill_filters(all_logs)
        event, person = self.event_filter.currentData(), self.person_filter.currentData()
        logs = [lg for lg in all_logs
                if (event is None or lg["event_name"] == event)
                and (person is None or lg["person"].strip().lower() == person)]
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
                if c == 0:
                    item.setData(_LOG_ID, lg["id"])  # rows can be re-sorted
                self.table.setItem(r, c, item)
        self.table.apply_sort()
        fit_columns(self.table)
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
        item = self.table.item(row, 0)
        log_id = item.data(_LOG_ID) if item else None
        log = next((lg for lg in self.manager.get_logs() if lg["id"] == log_id), None)
        if log is None:
            return
        dlg = LogEventDialog(self, self.manager, log=log)
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
        self.setStyleSheet(_DIALOG)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("Edit logged event" if self.editing else "Log an event")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#000000;")
        root.addWidget(title)

        # Event type: a dropdown when logging, fixed label when editing.
        if self.editing:
            row = self._field_row("Event")
            lbl = QLabel(self.log["event_name"])
            lbl.setStyleSheet("font-size:14px; font-weight:600; color:#1F2A33;")
            row.addWidget(lbl, 1)
        else:
            row = self._field_row("Event")
            self.type_combo = _dropdown()
            for t in self.manager.get_types():
                self.type_combo.addItem(t["name"], t["id"])
            # Start empty so the user picks the event deliberately.
            self.type_combo.setPlaceholderText("Choose an event")
            self.type_combo.setCurrentIndex(-1)
            self.type_combo.currentIndexChanged.connect(self._on_type_changed)
            row.addWidget(self.type_combo, 1)

        # Cost preview.
        cost_label = QLabel("Inventory cost")
        cost_label.setStyleSheet(
            "font-size:11px; font-weight:600; letter-spacing:0.6px; color:#000000;")
        root.addWidget(cost_label)
        self._cost_host = QWidget()
        self._cost_layout = QVBoxLayout(self._cost_host)
        self._cost_layout.setContentsMargins(0, 0, 0, 0)
        self._cost_layout.setSpacing(6)
        cost_scroll = QScrollArea()
        cost_scroll.setWidgetResizable(True)
        cost_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        cost_scroll.setStyleSheet(
            "QScrollArea { border:1px solid #E1E8ED; border-radius:2px;"
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
        self.comment_edit.setFixedHeight(70)
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

        if self.editing:  # only an existing entry has a logged timestamp
            lrow = self._field_row("Logged")
            logged_lbl = QLabel(self.log["logged_at"][:16])
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
                it.widget().hide()  # deleteLater alone leaves it visible a moment
                it.widget().deleteLater()
        self._rows = []
        lines = self._current_costs()
        if not lines:
            chosen = self.editing or self.type_combo.currentIndex() >= 0
            empty = QLabel("This event has no inventory cost." if chosen
                           else "Choose an event to see its inventory cost.")
            empty.setStyleSheet("color:#8895A0; font-size:13px; padding:10px;")
            self._cost_layout.addWidget(empty)
            self._cost_layout.addStretch(1)
            return
        for line in lines:
            self._cost_layout.addWidget(self._cost_row(line))
        if self.editing and any(line.get("deleted") for line in lines):
            # Re-saving costs would give back / take stock for an item that no
            # longer exists and zero its line, so this log's costs are frozen.
            for r in self._rows:
                r["spin"].setEnabled(False)
            note = QLabel("An item used by this event was deleted from the "
                          "inventory, so its quantities can't be changed.")
            note.setWordWrap(True)
            note.setStyleSheet("font-size:12px; color:#9A2A1E; padding:4px 10px;")
            self._cost_layout.addWidget(note)
        self._cost_layout.addStretch(1)

    def _cost_row(self, line: dict) -> QWidget:
        # When editing, stock already reflects this log's deduction, so the true
        # base availability is the current count plus what this log really took.
        base = line["available"] + (line["qty"] if self.editing else 0)

        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(10)

        name = QLabel(line["item_name"] + ("  (deleted item)" if line.get("deleted") else ""))
        name.setStyleSheet("font-size:13px; font-weight:600; color:#33404A;")
        name.setMinimumWidth(120)

        spin = QSpinBox()
        spin.setRange(0, 1000000)
        spin.setValue(line["qty"])
        spin.setFixedWidth(72)
        after = QLabel()
        after.setStyleSheet("font-size:12px;")
        after.setFixedWidth(130)  # fixed so qty + spin line up across rows

        def recompute(v=None):
            qty = spin.value()
            left = base - qty
            after.setText(f"{max(left, 0)} left of {base}")
            after.setStyleSheet(
                "font-size:12px; color:%s;" % ("#9A2A1E" if qty > base else "#5A6B72"))
        spin.valueChanged.connect(recompute)
        recompute()

        lay.addWidget(name)
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
        if not self.editing and self.type_combo.currentIndex() < 0:
            QMessageBox.warning(self, "Event required", "Please choose an event.")
            return
        lines = self._collect_lines()
        # When editing, only rewrite the costs if a quantity changed: otherwise
        # a comment edit would needlessly give back and re-take the stock.
        costs_changed = any(r["spin"].value() != r["line"]["qty"] for r in self._rows)
        short = [r for r in self._rows if r["spin"].value() > r["base"]]
        if short:
            names = ", ".join(f"{r['spin'].value()} {r['line']['item_name']} "
                              f"(have {r['base']})" for r in short)
            if not ConfirmDialog.ask(
                    self, title="Not enough in stock",
                    message="Some items are short: " + names + ".",
                    informative="Log it anyway?",
                    confirm_text="Log anyway", cancel_text="Cancel",
                    destructive=True):
                return
        person = self.person_edit.text().strip()
        comment = self.comment_edit.toPlainText().strip()
        event_date = self.date_edit.date().toString("yyyy-MM-dd")
        if self.editing:
            self.manager.update_log(self.log["id"], person, comment, event_date,
                                    cost_lines=lines if costs_changed else None)
        else:
            tid = self.type_combo.currentData()
            tname = self.manager.get_type(tid)["name"]
            self.manager.log_event(tid, tname, person, comment, event_date, lines)
        self.saved = True
        self.accept()

    def _on_delete(self):
        choice = ConfirmDialog.choose(
            self, title="Delete logged event",
            message="Delete this logged event?",
            informative="Add the items it consumed back to inventory?",
            confirm_text="Delete and restore", alt_text="Delete only")
        if choice is None:  # Cancel, Escape or closed: keep the entry
            return
        self.manager.delete_log(self.log["id"], restore=choice == "confirm")
        self.deleted = True
        self.accept()


class ManageEventTypesDialog(QDialog):
    """List of event types with add / edit / delete. Changes are held in a
    working copy and only written to the database on "Save and close"."""

    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        current = manager.get_types(include_archived=True)
        self._original = {t["id"]: t for t in current}
        # Working copy; "id" is None for types added in this session.
        self._types = [dict(t, costs=[dict(c) for c in t["costs"]]) for t in current]
        self._edited = set()   # ids of existing types changed here
        self._deleted = []     # ids of existing types removed here
        self._dirty = False
        self._build()

    def _build(self):
        self.setWindowTitle("Event types")
        self.setModal(True)
        self.resize(760, 520)
        self.setMinimumSize(560, 380)
        self.setStyleSheet(_DIALOG)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("Event types")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#000000;")
        head.addWidget(title)
        head.addStretch(1)
        add = QPushButton("+  New event")
        add.setStyleSheet(_PRIMARY)
        add.clicked.connect(self._add)
        head.addWidget(add)
        root.addLayout(head)

        self.list = HoverBorderTable(selectable=True)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setAlternatingRowColors(True)
        self.list.setShowGrid(False)
        self.list.verticalHeader().setVisible(False)
        self.list.setStyleSheet(HOVER_TABLE_STYLE)
        self.list.horizontalHeader().setFixedHeight(44)
        self.list.setWordWrap(True)
        self.list.setColumnCount(3)
        self.list.setHorizontalHeaderLabels(["Event", "Description", "Inventory cost"])
        self.list.doubleClicked.connect(lambda idx: self._edit(idx.row()))
        root.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        edit = QPushButton("Edit")
        edit.setStyleSheet(_SECONDARY)
        # selected_row(): a re-clicked (toggled-off) row must not count as chosen.
        edit.clicked.connect(lambda: self._edit(self.list.selected_row()))
        delete = QPushButton("Delete")
        delete.setStyleSheet(_DELETE_BTN)
        delete.clicked.connect(lambda: self._delete(self.list.selected_row()))
        buttons.addWidget(edit)
        buttons.addWidget(delete)
        buttons.addStretch(1)
        # "Close" while nothing changed; "Cancel" + "Save and close" after.
        self.close_btn = QPushButton("Close")
        self.close_btn.setStyleSheet(_SECONDARY)
        self.close_btn.clicked.connect(self.reject)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(_SECONDARY)
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn = QPushButton("Save and close")
        self.save_btn.setStyleSheet(_PRIMARY)
        self.save_btn.clicked.connect(self._save_and_close)
        for b in (self.close_btn, self.cancel_btn, self.save_btn):
            b.setAutoDefault(False)
            buttons.addWidget(b)
        root.addLayout(buttons)

        self._refresh()

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._refresh()

    def _refresh(self):
        self.close_btn.setVisible(not self._dirty)
        self.cancel_btn.setVisible(self._dirty)
        self.save_btn.setVisible(self._dirty)
        types = self._types
        self.list.setRowCount(len(types))
        for r, t in enumerate(types):
            cost = ", ".join(
                f"{c['qty']} {(self.manager.inventory.get_item(c['item_id']) or {}).get('name', '?')}"
                for c in t["costs"]) or "no cost"
            name = t["name"] + ("  (archived)" if t["is_archived"] else "")
            self.list.setItem(r, 0, QTableWidgetItem(name))
            self.list.setItem(r, 1, QTableWidgetItem(t["description"]))
            self.list.setItem(r, 2, QTableWidgetItem(cost))
        fit_columns(self.list)
        # Long descriptions wrap instead of pushing the cost column off-screen.
        self.list.setColumnWidth(1, min(max(self.list.columnWidth(1), 160), 320))
        self.list.resizeRowsToContents()

    def _add(self):
        dlg = EventTypeDialog(self, self.manager)
        dlg.exec()
        if dlg.saved:
            self._types.append({"id": None, "is_archived": False, **dlg.result})
            self._mark_dirty()

    def _edit(self, row):
        if not (0 <= row < len(self._types)):
            return
        t = self._types[row]
        dlg = EventTypeDialog(self, self.manager, event_type=t)
        dlg.exec()
        if dlg.saved:
            t.update(dlg.result)
            if t["id"] is not None:
                self._edited.add(t["id"])
            self._mark_dirty()

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
        self._types.pop(row)
        if t["id"] is not None:
            self._deleted.append(t["id"])
            self._edited.discard(t["id"])
        self._mark_dirty()

    def _save_and_close(self):
        """Write the held changes: deletions first, then each added or edited type."""
        m = self.manager
        try:
            for type_id in self._deleted:
                m.delete_type(type_id, reload=False)
            for t in self._types:
                if t["id"] is None:
                    type_id = m.add_type(t["name"], t["description"], reload=False)
                    for c in t["costs"]:
                        m.set_type_cost(type_id, c["item_id"], c["qty"], reload=False)
                elif t["id"] in self._edited:
                    m.update_type(t["id"], t["name"], t["description"],
                                  t["is_archived"], reload=False)
                    new = {c["item_id"]: c["qty"] for c in t["costs"]}
                    old = {c["item_id"] for c in self._original[t["id"]]["costs"]}
                    for item_id, qty in new.items():
                        m.set_type_cost(t["id"], item_id, qty, reload=False)
                    for item_id in old - set(new):  # removed recipe lines
                        m.set_type_cost(t["id"], item_id, 0, reload=False)
        except DatabaseError as e:
            QMessageBox.critical(self, "Could not save",
                                 f"Some changes may not have been saved.\n\n{e}")
        finally:
            m.reload()
        self._dirty = False
        self.accept()

    def reject(self):
        # Cancel, Escape and the window's X all land here.
        if self._dirty and not ConfirmDialog.ask(
                self, title="Discard changes?",
                message="Discard your changes to the event types?",
                confirm_text="Discard", cancel_text="Keep editing", destructive=True):
            return
        super().reject()


class EventTypeDialog(QDialog):
    """Create or edit an event type and its default cost recipe. Writes nothing:
    on Save it sets ``result`` for :class:`ManageEventTypesDialog` to hold."""

    def __init__(self, parent, manager, event_type=None):
        super().__init__(parent)
        self.manager = manager
        self.event_type = event_type
        self.editing = event_type is not None
        self.saved = False
        self.result = None  # {"name", "description", "costs": [{"item_id", "qty"}]}
        self._cost_rows = []  # dict(combo, spin)
        self._build()

    def _build(self):
        self.setWindowTitle("Event type")
        self.setModal(True)
        self.resize(520, 640)
        self.setMinimumSize(420, 480)
        self.setStyleSheet(_DIALOG)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(8)

        title = QLabel("Edit event" if self.editing else "New event")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#000000;")
        root.addWidget(title)

        self.name_edit = QLineEdit(self.event_type["name"] if self.editing else "")
        self.name_edit.setPlaceholderText("Event name")
        root.addWidget(self._labeled("Name", self.name_edit))

        self.desc_edit = QTextEdit(
            self.event_type["description"] if self.editing else "")
        self.desc_edit.setObjectName("CommentsField")
        self.desc_edit.setFixedHeight(90)
        self.desc_edit.setTabChangesFocus(True)
        root.addWidget(self._labeled("Description", self.desc_edit))

        cost_lbl = QLabel("Inventory needs")
        cost_lbl.setStyleSheet(
            "font-size:11px; font-weight:600; letter-spacing:0.6px; color:#000000;")
        root.addWidget(cost_lbl)
        self._cost_host = QWidget()
        self._cost_layout = QVBoxLayout(self._cost_host)
        self._cost_layout.setContentsMargins(0, 4, 0, 4)
        self._cost_layout.setSpacing(2)
        self._cost_layout.addStretch(1)  # keeps rows packed at the top
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.StyledPanel)
        scroll.setStyleSheet("QScrollArea { border:1px solid #E1E8ED;"
                             " border-radius:2px; background:#FAFCFD; }")
        scroll.setWidget(self._cost_host)
        scroll.setMinimumHeight(240)
        root.addWidget(scroll, 1)

        add_line = QPushButton("+  Add item cost")
        add_line.setStyleSheet(
            "QPushButton { background:#EEF4F6; color:#000000; border:1px solid #D8E2E8;"
            " border-radius:3px; padding:6px 14px; font-size:12px; font-weight:600;"
            " min-width:0px; }"
            " QPushButton:hover { background:#DCEBEB; border-color:#8FCFCF; }"
            " QPushButton:pressed { background:#CBE3E3; }")
        add_line.setCursor(Qt.CursorShape.PointingHandCursor)
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
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(10)
        combo = _dropdown()
        for it in self.manager.inventory.get_items():
            combo.addItem(it["name"], it["id"])
        if item_id is not None:
            idx = combo.findData(item_id)
            # A deleted item must not silently become the first item in the list.
            combo.setCurrentIndex(idx)
            if idx < 0:
                combo.setPlaceholderText("Deleted item: choose another or remove")
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
        self._cost_layout.insertWidget(self._cost_layout.count() - 1, row)  # above the stretch

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

        self.result = {
            "name": name,
            "description": description,
            "costs": [{"item_id": i, "qty": q} for i, q in new_costs.items()],
        }
        self.saved = True
        self.accept()
