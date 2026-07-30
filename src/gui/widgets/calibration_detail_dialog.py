"""Per-channel calibration dialog: pending panel + history + border plot.

Opened from the calibration tab. A freshly-added measurement sits in its own
"Awaiting decision" panel with inline Edit / Approve / Reject; approving or
rejecting moves it down into the history table. Decisions couple to the cell
status via ``on_decision``.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QAbstractItemView, QFrame, QWidget, QScrollArea, QGraphicsDropShadowEffect,
    QStyle, QStyledItemDelegate, QStyleOptionViewItem, QComboBox, QTextEdit,
)
from PyQt6.QtCore import Qt, QDate, QRegularExpression
from PyQt6.QtGui import QColor, QPen, QRegularExpressionValidator

from src.data.calibration_manager import (
    POTENTIAL_COLUMNS, STATUS_PASS, STATUS_FAIL, STATUS_AWAITING, STATUS_READY,
    STATUS_IN_USE, parse_float,
)
from src.gui.styles.dialog_styles import DIALOG_STYLE
from src.gui.widgets.calibration_plot import CalibrationPlot
from src.gui.widgets.confirm_dialog import ConfirmDialog
from src.gui.widgets.edit_row_dialog import CalendarDateEdit

# Status -> (background, foreground) for the pills. Colorblind-safe green/red.
STATUS_COLORS = {
    STATUS_PASS: ("#CDEFD6", "#1E6B3A"),
    STATUS_FAIL: ("#E04134", "#FFFFFF"),
    STATUS_AWAITING: ("#FFEAB3", "#7A5A14"),
    STATUS_READY: ("#E2EAEF", "#4A5A66"),
    STATUS_IN_USE: ("#CCE2F8", "#1E4E8C"),
}

# Small inline button styles for the pending row.
_APPROVE_STYLE = (
    "QPushButton{background:#0E9F6E;color:#FFFFFF;border:none;border-radius:6px;"
    "padding:5px 10px;font-weight:600;} QPushButton:hover{background:#0B8A5F;}"
    " QPushButton:disabled{background:#B7DCCB;color:#EAF5EF;}"
)
_REJECT_STYLE = (
    "QPushButton{background:#E0734D;color:#FFFFFF;border:none;border-radius:6px;"
    "padding:5px 10px;font-weight:600;} QPushButton:hover{background:#C75F3C;}"
    " QPushButton:disabled{background:#EBC6B6;color:#F6E9E2;}"
)
_NEUTRAL_STYLE = (
    "QPushButton{background:#EBEFF2;color:#33404A;border:none;border-radius:6px;"
    "padding:5px 10px;font-weight:600;} QPushButton:hover{background:#DCE3E8;}"
    " QPushButton:disabled{background:#F1F3F5;color:#AEB6BD;}"
)
_DELETE_STYLE = (
    "QPushButton{background:#F3D9D6;color:#9A2A1E;border:none;border-radius:6px;"
    "padding:5px 10px;font-weight:600;} QPushButton:hover{background:#E9C4C0;}"
    " QPushButton:disabled{background:#F0E7E6;color:#C9B6B3;}"
)


class _RowBorderDelegate(QStyledItemDelegate):
    """Marks the selected row with a thin black outline instead of a colored fill.

    Clearing the selected state before the base paint keeps each cell's own
    background/foreground (e.g. the colored Decision/Status pill), then a 1px
    border is drawn around the row (top/bottom on every cell; left on the first
    column, right on the last).
    """

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        # Never paint the selection / hover / focus fill — keep each cell's own
        # colors (e.g. the status pill). The selected row gets an outline below.
        opt.state &= ~(
            QStyle.StateFlag.State_Selected
            | QStyle.StateFlag.State_MouseOver
            | QStyle.StateFlag.State_HasFocus
        )
        super().paint(painter, opt, index)
        if not selected:
            return
        # Outline the row. Use the full cell rect (no inset) so the top/bottom
        # segments of adjacent cells join into one continuous line (an inset left
        # a 1px gap at every column boundary — the "dashed" look).
        painter.save()
        painter.setPen(QPen(QColor("#333333"), 1))
        rect = option.rect
        painter.drawLine(rect.left(), rect.top(), rect.right(), rect.top())
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        if index.column() == 0:
            painter.drawLine(rect.left(), rect.top(), rect.left(), rect.bottom())
        if index.column() == index.model().columnCount() - 1:
            painter.drawLine(rect.right() - 1, rect.top(), rect.right() - 1, rect.bottom())
        painter.restore()


def apply_row_border_selection(table) -> None:
    """Style ``table`` so the selected row shows a thin black outline, no fill."""
    table.setItemDelegate(_RowBorderDelegate(table))


class AddMeasurementDialog(QDialog):
    """Card-styled form to add a measurement (or edit an existing one's readings).

    Mirrors the cells-mapper editor look (frameless rounded card, gradient header).
    """

    def __init__(self, channel, manager, parent=None, measurement=None):
        super().__init__(parent)
        self.channel = channel
        self.manager = manager
        self.measurement = measurement  # dict when editing, None when adding
        self.saved = False
        self.result_decision = None  # verdict chosen on save (edit mode)
        self._build()
        if measurement:
            self._prefill(measurement)

    # ------------------------------------------------------------------ UI
    def _build(self):
        self.editing = self.measurement is not None
        self.setWindowTitle(
            f"{'Edit' if self.editing else 'Add'} measurement — channel {self.channel}"
        )
        self.setModal(True)
        self.resize(480, 640)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(DIALOG_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("DialogCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.addWidget(self._build_header())
        card_layout.addWidget(self._build_body(), 1)
        outer.addWidget(card)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(20, 50, 70, 90))
        card.setGraphicsEffect(shadow)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("DialogHeader")
        header.setFixedHeight(74)
        layout = QVBoxLayout(header)
        layout.setContentsMargins(24, 14, 24, 14)
        layout.setSpacing(2)
        title = QLabel("Edit measurement" if self.editing else "Add measurement")
        title.setObjectName("DialogTitle")
        subtitle = QLabel(f"Channel {self.channel}")
        subtitle.setObjectName("DialogSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return header

    def _build_body(self) -> QFrame:
        body = QFrame()
        body.setObjectName("DialogBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 20, 24, 18)
        body_layout.setSpacing(14)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        form = QVBoxLayout(content)
        form.setContentsMargins(0, 0, 8, 0)
        form.setSpacing(12)

        def field(label_text, widget):
            fr = QHBoxLayout()
            fr.setSpacing(12)
            lab = QLabel(label_text)
            lab.setObjectName("FieldLabel")
            lab.setWordWrap(True)
            lab.setFixedWidth(160)
            lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            fr.addWidget(lab, 0, Qt.AlignmentFlag.AlignTop)
            fr.addWidget(widget, 1)
            form.addLayout(fr)

        self.date_edit = CalendarDateEdit()
        self.date_edit.setObjectName("DateField")
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
        field("Date", self.date_edit)

        self.ic_edit = QLineEdit()
        field("IC number", self.ic_edit)

        self.by_edit = QLineEdit()
        field("Measured by", self.by_edit)

        # Only allow digits + one decimal separator (dot or comma) to be typed in
        # the numeric fields; parseability is still re-checked on save.
        num_validator = QRegularExpressionValidator(
            QRegularExpression(r"^\d*[.,]?\d*$"), self
        )

        self.current_edit = QLineEdit(str(self.manager.applied_current_default()))
        self.current_edit.setValidator(num_validator)
        field("Applied current [A]", self.current_edit)

        self.potential_edits = []
        for res in self.manager.resistances():
            edit = QLineEdit()
            edit.setPlaceholderText("measured potential")
            edit.setValidator(num_validator)
            field(f"Potential at {res:g} Ω", edit)
            self.potential_edits.append(edit)

        self.note_edit = QTextEdit()
        self.note_edit.setObjectName("CommentsField")  # reuse the bordered style
        self.note_edit.setMinimumHeight(70)
        self.note_edit.setTabChangesFocus(True)
        field("Note", self.note_edit)

        # When editing an existing measurement, let the user keep or change the
        # verdict here (add mode always starts as 'Awaiting decision').
        self.decision_combo = None
        if self.editing:
            self.decision_combo = QComboBox()
            self.decision_combo.addItems([STATUS_AWAITING, STATUS_PASS, STATUS_FAIL])
            if self.manager.is_locked(self.channel):
                self.decision_combo.setEnabled(False)
                self.decision_combo.setToolTip(
                    "Channel is In use — free the cell to change the verdict.")
            field("Decision", self.decision_combo)

        form.addStretch(1)
        scroll.setWidget(content)
        body_layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)  # don't let Cancel grab the green default look
        cancel.setDefault(False)
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setAutoDefault(True)
        save.setDefault(True)
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        body_layout.addLayout(buttons)
        return body

    # --------------------------------------------------------------- Data
    def _prefill(self, m: dict):
        if m.get("measured_date"):
            qd = QDate.fromString(m["measured_date"], "yyyy-MM-dd")
            if qd.isValid():
                self.date_edit.setDate(qd)
        self.ic_edit.setText(m.get("ic_number", ""))
        self.by_edit.setText(m.get("measured_by", ""))
        if m.get("applied_current") is not None:
            self.current_edit.setText(f"{m['applied_current']:g}")
        for edit, val in zip(self.potential_edits, m.get("potentials", [])):
            edit.setText("" if val is None else f"{val:g}")
        self.note_edit.setPlainText(m.get("note", ""))
        if self.decision_combo is not None:
            i = self.decision_combo.findText(m.get("status") or STATUS_AWAITING)
            if i >= 0:
                self.decision_combo.setCurrentIndex(i)

    def _values(self) -> dict:
        values = {
            "measured_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "ic_number": self.ic_edit.text().strip(),
            "measured_by": self.by_edit.text().strip(),
            "applied_current": self.current_edit.text().strip(),
            "note": self.note_edit.toPlainText().strip(),
        }
        for col, edit in zip(POTENTIAL_COLUMNS, self.potential_edits):
            values[col] = edit.text().strip()
        return values

    def _missing_required(self, values: dict) -> list:
        """Required fields left blank — everything except the IC number."""
        missing = []
        if not values.get("measured_by"):
            missing.append("Measured by")
        if not values.get("applied_current"):
            missing.append("Applied current [A]")
        for col, res in zip(POTENTIAL_COLUMNS, self.manager.resistances()):
            if not values.get(col):
                missing.append(f"Potential @ {res:g} Ω")
        return missing

    def _invalid_numbers(self, values: dict) -> list:
        """Numeric fields with non-empty but unparseable text (comma or dot ok)."""
        bad = []
        if values.get("applied_current") and parse_float(values["applied_current"]) is None:
            bad.append("Applied current [A]")
        for col, res in zip(POTENTIAL_COLUMNS, self.manager.resistances()):
            text = values.get(col, "")
            if text and parse_float(text) is None:
                bad.append(f"Potential @ {res:g} Ω")
        return bad

    def _save(self):
        values = self._values()
        missing = self._missing_required(values)
        if missing:
            QMessageBox.warning(
                self, "Missing fields",
                "Please fill in (only the IC number may be left empty):\n\n• "
                + "\n• ".join(missing),
            )
            return
        invalid = self._invalid_numbers(values)
        if invalid:
            QMessageBox.warning(
                self, "Invalid number",
                "Enter a valid number (comma or dot for decimals) in:\n\n• "
                + "\n• ".join(invalid),
            )
            return
        if self.measurement:
            decision = (self.decision_combo.currentText()
                        if self.decision_combo is not None else STATUS_AWAITING)
            ok = self.manager.update_measurement(
                self.measurement["id"], self.channel, values, decision=decision
            )
            self.result_decision = decision
        else:
            ok = self.manager.add_measurement(self.channel, values) is not None
        if ok:
            self.saved = True
            self.accept()
        else:
            QMessageBox.warning(
                self, "Save failed",
                "The measurement could not be saved. Please try again.",
            )

    # ---------------------------------------------------- Window dragging
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)


class CalibrationDetailDialog(QDialog):
    """Pending panel + history + plot for one channel."""

    def __init__(self, channel, manager, parent=None, on_decision=None):
        super().__init__(parent)
        self.channel = channel
        self.manager = manager
        # on_decision(channel, passed: bool) — lets the caller update the cell.
        self.on_decision = on_decision
        # Locked when the cell is In use: no new measurement / decision allowed.
        self.locked = manager.is_locked(channel)
        self.records = []
        self._decided = []
        self._pending = []
        self._build()
        self._reload()

    # ------------------------------------------------------------------ UI
    def _build(self):
        self.setWindowTitle(f"Channel {self.channel} — Calibration")
        self.setModal(True)
        self.resize(700, 740)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 16)
        outer.setSpacing(10)

        title = QLabel(f"Channel {self.channel} — Calibration")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #1F2A33;")
        outer.addWidget(title)

        if self.locked:
            banner = QLabel(
                "This channel is currently In use, free the cell (finish the "
                "experiment) before running a calibration."
            )
            banner.setWordWrap(True)
            banner.setStyleSheet(
                "background:#CCE2F8; color:#1E4E8C; border-radius:6px; padding:8px 12px;"
            )
            outer.addWidget(banner)

        self.plot = CalibrationPlot()
        outer.addWidget(self.plot)

        # --- Pending (awaiting decision) panel, shown above the history ---
        self.pending_label = QLabel("Awaiting decision")
        self.pending_label.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #7A5A14;"
        )
        outer.addWidget(self.pending_label)

        # A mini-table with the same headers as the history. Not selectable (no
        # highlight on click); the buttons below act on the awaiting measurement.
        self.pending_table = QTableWidget()
        self.pending_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pending_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.pending_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pending_table.verticalHeader().setVisible(False)
        self.pending_table.setStyleSheet("QTableWidget { background:#FFFDF5; }")
        pending_headers = ["Date", "IC number", "Measured by"] + \
            [f"ΔV% {r:g}Ω" for r in self.manager.resistances()] + ["Auto-check"]
        self.pending_table.setColumnCount(len(pending_headers))
        self.pending_table.setHorizontalHeaderLabels(pending_headers)
        self.pending_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        outer.addWidget(self.pending_table)

        # Decision buttons below the pending table (act on the awaiting row).
        self.pending_buttons = QWidget()
        pb = QHBoxLayout(self.pending_buttons)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.setSpacing(8)
        self.p_edit = self._pending_button("Edit", _NEUTRAL_STYLE, self._edit_pending)
        self.p_delete = self._pending_button("Delete", _DELETE_STYLE, self._delete_pending)
        self.p_approve = self._pending_button(
            "✓ Approve", _APPROVE_STYLE, lambda: self._decide_pending(True))
        self.p_reject = self._pending_button(
            "✗ Reject", _REJECT_STYLE, lambda: self._decide_pending(False))
        pb.addWidget(self.p_edit)
        pb.addWidget(self.p_delete)
        pb.addWidget(self.p_approve)
        pb.addWidget(self.p_reject)
        pb.addStretch(1)
        outer.addWidget(self.pending_buttons)

        # --- History (decided measurements) ---
        history_label = QLabel("History")
        history_label.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: #4A5A66;"
        )
        outer.addWidget(history_label)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        # Selected row = thin black outline (keeps the Decision pill colors).
        apply_row_border_selection(self.table)
        self.table.itemSelectionChanged.connect(self._on_history_selection)
        # Double-click a decided row to flip its verdict (fix a mis-click).
        self.table.cellDoubleClicked.connect(self._on_history_double_clicked)
        self.table.setToolTip("Double-click a row to edit the measurement and its decision.")
        headers = ["Date", "IC number", "Measured by"] + \
            [f"ΔV% {r:g}Ω" for r in self.manager.resistances()] + ["Decision"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        outer.addWidget(self.table, 1)

        # --- Bottom buttons ---
        buttons = QHBoxLayout()
        self.add_btn = QPushButton("Add measurement")
        self.add_btn.setStyleSheet(_NEUTRAL_STYLE)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.clicked.connect(self._add)
        self.delete_btn = QPushButton("Delete history")
        self.delete_btn.setStyleSheet(_DELETE_STYLE)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.clicked.connect(self._delete_selected_history)
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(_NEUTRAL_STYLE)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)

        buttons.addWidget(self.add_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.delete_btn)
        buttons.addWidget(close_btn)
        outer.addLayout(buttons)

    # --------------------------------------------------------------- Data
    def _reload(self):
        self.records = self.manager.get_history(self.channel)
        pending = [r for r in self.records if r["status"] == STATUS_AWAITING]
        self._decided = [r for r in self.records if r["status"] in (STATUS_PASS, STATUS_FAIL)]

        # Pending panel (mini-table + buttons below). Only shown when awaiting.
        self._pending = pending
        show = bool(pending)
        self.pending_label.setVisible(show)
        self.pending_table.setVisible(show)
        self.pending_buttons.setVisible(show)
        self._fill_pending_table(pending)
        self.p_edit.setEnabled(show)
        self.p_delete.setEnabled(show)
        self.p_approve.setEnabled(show and not self.locked)
        self.p_reject.setEnabled(show and not self.locked)

        # One awaiting measurement at a time: block Add while one is pending
        # (also blocked when the cell is In use).
        self.add_btn.setEnabled(not self.locked and not show)
        if self.locked:
            self.add_btn.setToolTip("Channel is In use — free the cell before calibrating.")
        elif show:
            self.add_btn.setToolTip("Approve or reject the awaiting measurement before adding another.")
        else:
            self.add_btn.setToolTip("")

        # History table (decided only)
        self.table.setRowCount(len(self._decided))
        for r, rec in enumerate(self._decided):
            col = 0
            for value in (rec["measured_date"], rec["ic_number"], rec["measured_by"]):
                self.table.setItem(r, col, QTableWidgetItem(value))
                col += 1
            for d in rec["deltas"]:
                item = QTableWidgetItem("—" if d is None else f"{d:.2f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, col, item)
                col += 1
            item = QTableWidgetItem(rec["status"])
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            bg, fg = STATUS_COLORS.get(rec["status"], ("#E2EAEF", "#4A5A66"))
            item.setBackground(QColor(bg))
            item.setForeground(QColor(fg))
            self.table.setItem(r, col, item)

        # Select the first history row so "Delete history" has a clear target.
        # Block signals so this doesn't hijack the plot (set to focus below).
        if self._decided:
            self.table.blockSignals(True)
            self.table.selectRow(0)
            self.table.blockSignals(False)
            self.delete_btn.setEnabled(True)
        else:
            self.table.clearSelection()
            self.delete_btn.setEnabled(False)

        # Plot focuses the pending measurement (what you're deciding), else the
        # most recent decided one.
        focus = pending[0] if pending else (self._decided[0] if self._decided else None)
        if focus is not None:
            self._show_plot(focus)
        else:
            self.plot.set_data(self.manager.resistances(), self.manager.bounds(), [])

    _VERDICT = {
        "pass": ("Within limits", "#CDEFD6", "#1E6B3A"),
        "fail": ("Out of limits", "#E04134", "#FFFFFF"),
        "incomplete": ("Incomplete", "#E2EAEF", "#4A5A66"),
    }

    def _fill_pending_table(self, pending: list):
        bounds = self.manager.bounds()
        self.pending_table.setRowCount(len(pending))
        for r, rec in enumerate(pending):
            col = 0
            for value in (rec["measured_date"], rec["ic_number"], rec["measured_by"]):
                self.pending_table.setItem(r, col, QTableWidgetItem(value))
                col += 1
            for i, d in enumerate(rec["deltas"]):
                item = QTableWidgetItem("—" if d is None else f"{d:.2f}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                lo, hi = bounds[i] if i < len(bounds) else (None, None)
                out = d is not None and (
                    (lo is not None and d < lo) or (hi is not None and d > hi)
                )
                if out:  # tint the reading that breaks a limit
                    item.setBackground(QColor("#F7D6D2"))
                    item.setForeground(QColor("#9A2A1E"))
                self.pending_table.setItem(r, col, item)
                col += 1
            text, bg, fg = self._VERDICT.get(rec["auto_eval"], ("", "#E2EAEF", "#4A5A66"))
            verdict = QTableWidgetItem(text)
            verdict.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            verdict.setBackground(QColor(bg))
            verdict.setForeground(QColor(fg))
            self.pending_table.setItem(r, col, verdict)
            self.pending_table.setRowHeight(r, 32)
        # Hug the content (header + rows) and reserve room for the horizontal
        # scrollbar so, on a narrow window, it can't cover the single row.
        header_h = self.pending_table.horizontalHeader().sizeHint().height()
        scrollbar_h = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        self.pending_table.setFixedHeight(
            header_h + len(pending) * 32 + scrollbar_h + 14
        )

    def _pending_button(self, text, style, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setStyleSheet(style)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    def _current_pending(self):
        # Normally exactly one; the buttons act on the most recent awaiting one.
        return self._pending[0] if self._pending else None

    def _edit_pending(self):
        rec = self._current_pending()
        if rec is not None:
            self._edit(rec)

    def _delete_pending(self):
        rec = self._current_pending()
        if rec is not None:
            self._delete(rec)

    def _decide_pending(self, passed: bool):
        rec = self._current_pending()
        if rec is not None:
            self._decide(rec, passed)

    def _show_plot(self, rec: dict):
        self.plot.set_data(self.manager.resistances(), self.manager.bounds(), rec["deltas"])

    def _selected_history(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        return self._decided[idx] if 0 <= idx < len(self._decided) else None

    def _on_history_selection(self):
        rec = self._selected_history()
        self.delete_btn.setEnabled(rec is not None)
        if rec is not None:
            self._show_plot(rec)

    def _on_history_double_clicked(self, row, _col):
        """Edit a decided measurement's values (and keep/change its verdict)."""
        if 0 <= row < len(self._decided):
            self._edit(self._decided[row])

    # ------------------------------------------------------------- Actions
    def _add(self):
        dlg = AddMeasurementDialog(self.channel, self.manager, self)
        dlg.exec()
        if dlg.saved:
            self._reload()

    def _edit(self, rec: dict):
        old_decision = rec["status"]
        dlg = AddMeasurementDialog(self.channel, self.manager, self, measurement=rec)
        dlg.exec()
        if not dlg.saved:
            return
        # Only touch the cell when the verdict actually changed to Pass/Fail, so
        # editing a reading (and keeping the verdict) doesn't re-trigger coupling.
        decision = dlg.result_decision
        if (decision in (STATUS_PASS, STATUS_FAIL)
                and decision != old_decision
                and callable(self.on_decision)):
            self.on_decision(self.channel, decision == STATUS_PASS)
        self._reload()

    def _delete(self, rec: dict):
        confirmed = ConfirmDialog.ask(
            self,
            title="Delete measurement",
            message="Delete this calibration measurement permanently?",
            informative="This action cannot be undone.",
            confirm_text="Yes, delete",
            cancel_text="Cancel",
            destructive=True,
            subtitle="",
        )
        if confirmed and self.manager.delete_measurement(rec["id"]):
            self._reload()

    def _delete_selected_history(self):
        rec = self._selected_history()
        if rec is not None:
            self._delete(rec)

    def _decide(self, rec: dict, passed: bool):
        decision = STATUS_PASS if passed else STATUS_FAIL
        if not self.manager.set_decision(rec["id"], decision):
            QMessageBox.warning(self, "Failed", "Could not save the decision.")
            return
        # Couple to the cell status (In repair / Available) via the caller.
        if callable(self.on_decision):
            self.on_decision(self.channel, passed)
        self._reload()
