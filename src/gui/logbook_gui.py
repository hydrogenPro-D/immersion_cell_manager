"""IC Logbook tab: historical experiments.

A nested tab set: a live-computed **Summary** sub-tab, then one sub-tab per
project category, each a read-only table of that category's experiments. Phase 1
reads from CSV via :class:`LogbookManager`; the GUI is unaware of the source.
"""

from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QGraphicsDropShadowEffect, QScrollArea, QDialog, QLineEdit, QPushButton,
    QMessageBox, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QTextEdit,
    QStyleOptionComboBox, QSizeGrip,
)
from PyQt6.QtCore import Qt, QRegularExpression, QTimer, QDate, QEvent, QPointF
from PyQt6.QtGui import QColor, QRegularExpressionValidator, QPen, QMouseEvent

from src.gui.styles.tab_styles import TAB_STYLE
from src.gui.styles.dialog_styles import DIALOG_STYLE
from src.gui.widgets.confirm_dialog import ConfirmDialog
from src.gui.widgets.edit_row_dialog import CalendarDateEdit
from src.data.logbook_manager import STANDARD_COLUMNS, EXTRA_COLUMNS

_SUBTAB_STYLE = (
    "QTabWidget::pane { border: 1px solid #E1E8ED; top: -1px; }"
    "QTabBar::tab { padding: 8px 16px; margin-right: 2px; background: #F5F5F5;"
    " color: #1F1F1F; font-weight: 500; border-top-left-radius: 6px;"
    " border-top-right-radius: 6px; }"
    "QTabBar::tab:selected { background: #FFFFFF; color: #3FA3A3;"
    " border-bottom: 2px solid #3FA3A3; }"
    "QTabBar::tab:hover { background: #ECECEC; }"
)

_TABLE_STYLE = (
    "QTableWidget { background:#FFFFFF; border:1px solid #E1E8ED;"
    " border-radius:8px; gridline-color:#EEF2F5; }"
    "QHeaderView::section { background:#E2EAEF; color:#4A5A66;"
    " padding:6px 8px; border:none; font-weight:600; }"
)

# Secondary button. Enabled: teal-tinted with a teal border so it clearly reads
# as active; disabled: flat, borderless grey so the state change is obvious.
_SECONDARY_BTN = (
    "QPushButton { background:#E4F2F2; color:#1A5E5E; border:1px solid #6FBFBF;"
    " border-radius:10px; padding:9px 20px; font-size:12px; font-weight:700;"
    " letter-spacing:0.4px; }"
    " QPushButton:hover { background:#D2EAEA; border-color:#4FB0B0; }"
    " QPushButton:disabled { background:#F1F3F5; color:#AEB6BD; border:none; }"
)


class _LogbookDateEdit(CalendarDateEdit):
    """The cells-mapping calendar picker (📅 popup, read-only field), but the
    value is optional and may be in the past ("Experiment finished on").

    Empty is Qt's special-value trick at ``minimumDate``; Delete/Backspace clears
    it. Unlike the planned-end picker, past dates are allowed.
    """

    UNSET = QDate(1900, 1, 1)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._opening = False
        self.setObjectName("DateField")  # match the other input fields' styling
        self.setDisplayFormat("yyyy-MM-dd")
        self.setMinimumDate(self.UNSET)
        self.setSpecialValueText("not set")
        self.setDate(self.UNSET)
        self.calendarWidget().installEventFilter(self)  # open on current month
        # Clicks land on the QDateEdit (not the inner field) so a click anywhere
        # opens the calendar, not just the icon.
        line_edit = self.lineEdit()
        if line_edit is not None:
            line_edit.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def is_set(self) -> bool:
        return self.date() != self.UNSET

    def clear_date(self) -> None:
        self.setDate(self.UNSET)

    def date_string(self) -> str:
        return self.date().toString("yyyy-MM-dd") if self.is_set() else ""

    def set_from_string(self, text: str) -> None:
        d = QDate.fromString((text or "")[:10], "yyyy-MM-dd")
        self.setDate(d if d.isValid() else self.UNSET)

    def mousePressEvent(self, event):
        # Open the calendar popup for a click anywhere in the field by
        # forwarding a synthetic click onto the drop-down arrow.
        if self.isEnabled() and not self._opening:
            self._opening = True
            try:
                opt = QStyleOptionComboBox()
                opt.initFrom(self)
                arrow = self.style().subControlRect(
                    QStyle.ComplexControl.CC_ComboBox, opt,
                    QStyle.SubControl.SC_ComboBoxArrow, self)
                pos = QPointF(arrow.center())
                gpos = QPointF(self.mapToGlobal(arrow.center()))
                super().mousePressEvent(QMouseEvent(
                    QEvent.Type.MouseButtonPress, pos, gpos,
                    Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier))
            finally:
                self._opening = False
            return
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        if (obj is self.calendarWidget()
                and event.type() == QEvent.Type.Show and not self.is_set()):
            today = QDate.currentDate()
            obj.setCurrentPage(today.year(), today.month())
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.clear_date()
            event.accept()
            return
        event.ignore()


class _RowHoverBorderDelegate(QStyledItemDelegate):
    """Outlines whole rows with a border (no background change): a thin one on
    the hovered row, a thicker/darker one on the selected row. No fills."""

    HOVER = QColor("#3FA3A3")           # thin teal on hover
    SELECTED = QColor("#1F6B6B")        # thicker darker teal on the selected row

    def paint(self, painter, option, index):
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        opt = QStyleOptionViewItem(option)
        opt.state &= ~(QStyle.StateFlag.State_MouseOver
                       | QStyle.StateFlag.State_Selected)  # no hover / selection fill
        super().paint(painter, opt, index)

        if selected:
            self._border(painter, option, index, self.SELECTED, 2)
        elif getattr(self.parent(), "_hover_row", -1) == index.row():
            self._border(painter, option, index, self.HOVER, 1)

    @staticmethod
    def _border(painter, option, index, color, width):
        painter.save()
        painter.setPen(QPen(color, width))
        rect = option.rect
        painter.drawLine(rect.left(), rect.top(), rect.right(), rect.top())
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        if index.column() == 0:
            painter.drawLine(rect.left(), rect.top(), rect.left(), rect.bottom())
        if index.column() == index.model().columnCount() - 1:
            painter.drawLine(rect.right() - 1, rect.top(), rect.right() - 1, rect.bottom())
        painter.restore()


class _HoverBorderTable(QTableWidget):
    """Table that outlines the hovered (and, if selectable, the selected) row with
    a border, no background fill. Selectable tables toggle: clicking the already-
    selected row deselects it."""

    def __init__(self, parent=None, selectable=False):
        super().__init__(parent)
        self._hover_row = -1
        self._toggle_row = -1
        self._selectable = selectable
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        # No per-cell hover highlight, we draw a whole-row border instead. The
        # native style paints cell hover from the view's own hover index, so turn
        # off WA_Hover and don't let the base mouseMove set a hovered cell.
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, False)
        self.setItemDelegate(_RowHoverBorderDelegate(self))
        if selectable:
            self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        else:
            self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

    def selected_row(self) -> int:
        if not self._selectable:
            return -1
        rows = self.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _set_hover(self, row: int) -> None:
        if row != self._hover_row:
            self._hover_row = row
            self.viewport().update()

    def mousePressEvent(self, event):
        # Remember if this press landed on the already-selected row, so the
        # release can toggle it off. Clearing here doesn't stick, the base
        # handler re-selects the row on release.
        self._toggle_row = -1
        if self._selectable and event.button() == Qt.MouseButton.LeftButton:
            idx = self.indexAt(event.position().toPoint())
            r = idx.row() if idx.isValid() else -1
            if r != -1 and r == self.selected_row():
                self._toggle_row = r
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # Toggle off a re-click of the selected row, after the base handler has
        # done its own (re)selection on release.
        super().mouseReleaseEvent(event)
        if (self._toggle_row != -1 and event.button() == Qt.MouseButton.LeftButton
                and self.indexAt(event.position().toPoint()).row() == self._toggle_row):
            self.clearSelection()
            self.viewport().update()
        self._toggle_row = -1

    def mouseMoveEvent(self, event):
        # Track the row ourselves; intentionally do NOT chain to the base handler
        # (it would set a per-cell hover state that the style would highlight).
        idx = self.indexAt(event.position().toPoint())
        self._set_hover(idx.row() if idx.isValid() else -1)

    def leaveEvent(self, event):
        self._set_hover(-1)
        super().leaveEvent(event)


class LogbookTab(QWidget):
    """Historical experiment logbook: Summary + one table per category."""

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
        root.setSpacing(12)
        root.addWidget(self._build_header())

        # Add / Update act on whichever category tab is open (hidden on Summary).
        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        self.update_btn = QPushButton("Update")
        self.update_btn.setStyleSheet(_SECONDARY_BTN)
        self.update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_btn.setEnabled(False)
        self.update_btn.clicked.connect(self._on_update_clicked)
        self.add_btn = QPushButton("＋  Add")
        self.add_btn.setObjectName("PrimaryButton")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.clicked.connect(self._on_add_clicked)
        toolbar.addWidget(self.update_btn)
        toolbar.addWidget(self.add_btn)
        root.addLayout(toolbar)

        self.sub_tabs = QTabWidget()
        self.sub_tabs.setStyleSheet(_SUBTAB_STYLE)
        self.sub_tabs.setUsesScrollButtons(True)
        self.sub_tabs.currentChanged.connect(lambda *_a: self._sync_toolbar())
        self._populate_sub_tabs()
        root.addWidget(self.sub_tabs, 1)
        self._sync_toolbar()

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("PageHeader")
        header.setFixedHeight(70)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        title = QLabel("IC Logbook")
        title.setObjectName("PageTitle")
        layout.addWidget(title, 1)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(63, 163, 163, 90))
        header.setGraphicsEffect(shadow)
        return header

    def _populate_sub_tabs(self) -> None:
        self.sub_tabs.clear()
        self.sub_tabs.addTab(self._build_summary(), "Summary")
        for category in self.manager.get_categories():
            self.sub_tabs.addTab(self._build_category(category), category)

    # --------------------------------------------------------- Category tab
    def _make_table(self, selectable: bool = False) -> QTableWidget:
        table = _HoverBorderTable(selectable=selectable)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(True)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        table.setStyleSheet(_TABLE_STYLE)
        return table

    def _build_category(self, category: str) -> QWidget:
        cols = self.manager.get_columns(category)
        rows = self.manager.get_experiments(category)

        table = self._make_table(selectable=True)
        # Leading "#" row-counter column (artificial, not part of the data).
        table.setColumnCount(len(cols) + 1)
        table.setHorizontalHeaderLabels(["#"] + [label for _, label in cols])
        table.setRowCount(len(rows))
        for r, exp in enumerate(rows):
            num = QTableWidgetItem(str(r + 1))
            num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            num.setForeground(QColor("#8A97A0"))
            table.setItem(r, 0, num)
            for c, (field, _) in enumerate(cols):
                item = QTableWidgetItem((exp.get(field) or "").strip())
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                table.setItem(r, c + 1, item)

        header = table.horizontalHeader()
        # Interactive so the user can drag any column border to resize it. Start
        # from natural widths, then give the long free-text columns a comfortable
        # readable default and cap any single-cell outlier so it can't blow up a
        # column. (+1 everywhere for the leading counter column.)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # Last column fills any leftover width so the table always reaches the
        # right edge (no empty gap on wide monitors); a scrollbar appears instead
        # when the columns are wider than the viewport.
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(36)
        table.resizeColumnsToContents()
        default_widths = {"ic_id": 240, "notes": 340, "protocol": 180,
                          "archived_in": 160, "plot": 150, "synthesis_recipe": 200}
        for c, (field, _) in enumerate(cols):
            if field in default_widths:
                table.setColumnWidth(c + 1, default_widths[field])
        for c in range(table.columnCount()):
            if table.columnWidth(c) > 420:
                table.setColumnWidth(c, 420)
        table.resizeRowsToContents()
        # Double-click a row to edit it; selection drives the global Update button.
        table.doubleClicked.connect(
            lambda idx, c=category: self._edit_experiment(c, idx.row()))
        table.selectionModel().selectionChanged.connect(
            lambda *_a: self._sync_toolbar())
        # Start scrolled to the newest (bottom) rows.
        QTimer.singleShot(0, table.scrollToBottom)
        return table

    # --------------------------------------------------------- Global toolbar
    def _current_category(self):
        """(category, table) for the open category tab, or (None, None)."""
        w = self.sub_tabs.currentWidget()
        if isinstance(w, _HoverBorderTable) and getattr(w, "_selectable", False):
            return self.sub_tabs.tabText(self.sub_tabs.currentIndex()), w
        return None, None

    def _sync_toolbar(self) -> None:
        category, table = self._current_category()
        show = category is not None
        self.add_btn.setVisible(show)
        self.update_btn.setVisible(show)
        if show:
            self.update_btn.setEnabled(table.selected_row() != -1)

    def _on_add_clicked(self):
        category, _ = self._current_category()
        if category is not None:
            self._add_experiment(category)

    def _on_update_clicked(self):
        category, table = self._current_category()
        if category is not None and table.selected_row() != -1:
            self._edit_experiment(category, table.selected_row())

    # ------------------------------------------------------ Experiment edits
    def _refresh_category(self, category: str) -> None:
        """Reload from the DB and rebuild the Summary + this category tab."""
        self.manager.reload()
        self.sub_tabs.removeTab(0)
        self.sub_tabs.insertTab(0, self._build_summary(), "Summary")
        for i in range(self.sub_tabs.count()):
            if self.sub_tabs.tabText(i) == category:
                self.sub_tabs.removeTab(i)
                self.sub_tabs.insertTab(i, self._build_category(category), category)
                self.sub_tabs.setCurrentIndex(i)
                break
        self._sync_toolbar()

    def _add_experiment(self, category: str) -> None:
        dlg = ExperimentDialog(self, category=category, values={}, adding=True)
        dlg.exec()
        if dlg.saved:
            self.manager.add_experiment(category, dlg.result_values)
            self._refresh_category(category)

    def _edit_experiment(self, category: str, row: int) -> None:
        rows = self.manager.get_experiments(category)
        if not (0 <= row < len(rows)):
            return
        exp = rows[row]
        dlg = ExperimentDialog(self, category=category, values=exp, adding=False)
        dlg.exec()
        if dlg.deleted:
            self.manager.delete_experiment(exp.get("id"))
            self._refresh_category(category)
        elif dlg.saved:
            self.manager.update_experiment(exp.get("id"), dlg.result_values)
            self._refresh_category(category)

    # ---------------------------------------------------------- Summary tab
    def _build_summary(self) -> QWidget:
        data = self.manager.get_summary()

        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(14)

        # Live counter chips.
        chips = QHBoxLayout()
        chips.setSpacing(12)
        chips.addWidget(self._stat_chip(
            "Total testing time", f"{data['total_hours']:,.0f} h"))
        chips.addWidget(self._stat_chip(
            "Number of experiments", f"{data['total_count']:,}"))
        chips.addStretch(1)
        layout.addLayout(chips)

        # Per-category breakdown.
        cat_table = self._make_table()
        cat_table.setColumnCount(3)
        cat_table.setHorizontalHeaderLabels(
            ["Category", "Number of ICs", "Total testing time [h]"])
        per = data["per_category"]
        cat_table.setRowCount(len(per))
        for r, row in enumerate(per):
            cat_table.setItem(r, 0, QTableWidgetItem(row["category"]))
            self._num_cell(cat_table, r, 1, f"{row['count']:,}")
            self._num_cell(cat_table, r, 2, f"{row['hours']:,.1f}")
        cat_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        cat_table.resizeRowsToContents()
        cat_table.setMinimumHeight(min(60 + 30 * len(per), 640))
        layout.addWidget(cat_table)

        # Scoreboard (manual historical snapshots), double-click a row to edit
        # or delete it; "Add snapshot" (above-right) appends one dated today.
        sb_head = QHBoxLayout()
        sb_head.addWidget(self._section_label("Scoreboard"))
        sb_head.addStretch(1)
        add_snap_btn = QPushButton("＋  Add")
        add_snap_btn.setObjectName("PrimaryButton")
        add_snap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_snap_btn.clicked.connect(self._add_scoreboard)
        sb_head.addWidget(add_snap_btn)
        layout.addLayout(sb_head)
        scoreboard = self.manager.get_scoreboard()
        sb = self._make_table()
        headers = ["Date", "Days since ID intro", "Total testing time [h]",
                   "Number of ICs"]
        keys = ["date", "days_since_id_intro", "total_testing_time_h",
                "number_of_ics"]
        sb.setColumnCount(len(headers))
        sb.setHorizontalHeaderLabels(headers)
        sb.setRowCount(len(scoreboard))
        for r, row in enumerate(scoreboard):
            for c, k in enumerate(keys):
                item = QTableWidgetItem((row.get(k) or "").strip())
                if c > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                sb.setItem(r, c, item)
        sb.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        sb.resizeRowsToContents()
        sb.setMinimumHeight(min(60 + 30 * max(len(scoreboard), 1), 300))
        sb.setToolTip("Double-click a snapshot to edit or delete it.")
        sb.cellDoubleClicked.connect(lambda r, _c: self._edit_scoreboard(r))
        layout.addWidget(sb)

        layout.addStretch(1)
        page.setWidget(inner)
        return page

    # --------------------------------------------------- Scoreboard editing
    def _refresh_summary(self) -> None:
        """Rebuild only the Summary sub-tab (after a scoreboard change)."""
        self.sub_tabs.removeTab(0)
        self.sub_tabs.insertTab(0, self._build_summary(), "Summary")
        self.sub_tabs.setCurrentIndex(0)

    def _edit_scoreboard(self, row: int) -> None:
        rows = self.manager.get_scoreboard()
        if not (0 <= row < len(rows)):
            return
        rec = rows[row]
        dlg = ScoreboardDialog(
            self, adding=False,
            date_str=rec.get("date", ""), days_str=rec.get("days_since_id_intro", ""),
            time_val=rec.get("total_testing_time_h", ""),
            ics_val=rec.get("number_of_ics", ""),
        )
        dlg.exec()
        if dlg.deleted:
            self.manager.delete_scoreboard(row)
            self._refresh_summary()
        elif dlg.saved:
            self.manager.update_scoreboard(row, dlg.result_time, dlg.result_ics)
            self._refresh_summary()

    def _add_scoreboard(self) -> None:
        dlg = ScoreboardDialog(self, adding=True)
        dlg.exec()
        if dlg.saved:
            self.manager.add_scoreboard(dlg.result_time, dlg.result_ics)
            self._refresh_summary()

    @staticmethod
    def _num_cell(table, row, col, text) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(row, col, item)

    @staticmethod
    def _stat_chip(label: str, value: str) -> QFrame:
        chip = QFrame()
        chip.setStyleSheet(
            "QFrame { background:#F0F6F6; border:1px solid #D8E7E7;"
            " border-radius:10px; }")
        lay = QVBoxLayout(chip)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(2)
        v = QLabel(value)
        v.setStyleSheet("font-size:18px; font-weight:700; color:#256; border:none;"
                        " background:transparent;")
        k = QLabel(label)
        k.setStyleSheet("font-size:11px; color:#6B7A85; border:none;"
                        " background:transparent;")
        lay.addWidget(v)
        lay.addWidget(k)
        return chip

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size:13px; font-weight:600; color:#4A5A66;")
        return lbl

    # --------------------------------------------------------------- Data
    def reload_data(self) -> None:
        """Re-read the source and rebuild the sub-tabs."""
        self.manager.reload()
        self._populate_sub_tabs()


class ScoreboardDialog(QDialog):
    """Add / edit a scoreboard snapshot.

    Only the two manual values (Total testing time, Number of ICs) are editable;
    Date and Days-since-intro are read-only (auto-set today for a new snapshot).
    Card-styled to match the other dialogs.
    """

    _DELETE_STYLE = (
        "QPushButton{background:#F3D9D6;color:#9A2A1E;border:1px solid #E7C6C1;"
        "border-radius:8px;padding:8px 16px;font-weight:600;}"
        " QPushButton:hover{background:#E9C4C0;}"
    )

    def __init__(self, parent=None, *, adding=False, date_str="", days_str="",
                 time_val="", ics_val=""):
        super().__init__(parent)
        self.adding = adding
        self.saved = False
        self.deleted = False
        self.result_time = None
        self.result_ics = None
        self._date_str = date_str
        self._days_str = days_str
        self._time_val = time_val
        self._ics_val = ics_val
        self._build()

    def _build(self):
        self.setWindowTitle("Scoreboard snapshot")
        self.setModal(True)
        self.resize(430, 320)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # No header: round the body on top and give it a full border so it still
        # reads as a clean card.
        self.setStyleSheet(DIALOG_STYLE + (
            "QFrame#DialogBody { border-top-left-radius: 12px;"
            " border-top-right-radius: 12px; border-top: 1px solid #D8E2E8; }"
        ))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(0)
        card = QFrame()
        card.setObjectName("DialogCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._body(), 1)
        outer.addWidget(card)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(20, 50, 70, 90))
        card.setGraphicsEffect(shadow)

    def _body(self) -> QFrame:
        body = QFrame()
        body.setObjectName("DialogBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 20, 24, 18)
        bl.setSpacing(12)

        # Adding has only two fields, so a title keeps the card from looking bare.
        if self.adding:
            title = QLabel("Add new entry")
            title.setStyleSheet(
                "font-size:16px; font-weight:700; color:#1F6B6B;"
                " border:none; background:transparent;")
            bl.addWidget(title)

        def field(label_text, widget):
            row = QHBoxLayout()
            row.setSpacing(12)
            lab = QLabel(label_text)
            lab.setObjectName("FieldLabel")
            lab.setFixedWidth(160)
            row.addWidget(lab)
            row.addWidget(widget, 1)
            bl.addLayout(row)

        if not self.adding:
            d = QLineEdit(self._date_str)
            d.setReadOnly(True)
            field("Date", d)
            days = QLineEdit(self._days_str)
            days.setReadOnly(True)
            field("Days since ID intro", days)

        self.time_edit = QLineEdit(str(self._time_val))
        self.time_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"^\d*[.,]?\d*$"), self))
        field("Total testing time [h]", self.time_edit)

        self.ics_edit = QLineEdit(str(self._ics_val))
        self.ics_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"^\d*$"), self))
        field("Number of ICs", self.ics_edit)

        bl.addStretch(1)

        cancel = QPushButton("Cancel")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setDefault(True)
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._on_save)

        # Delete on the left, Cancel in the middle, Save on the right.
        buttons = QHBoxLayout()
        if not self.adding:
            delete = QPushButton("Delete")
            delete.setStyleSheet(self._DELETE_STYLE)
            delete.setCursor(Qt.CursorShape.PointingHandCursor)
            delete.setAutoDefault(False)
            delete.clicked.connect(self._on_delete)
            buttons.addWidget(delete)
            buttons.addStretch(1)
            buttons.addWidget(cancel)
            buttons.addStretch(1)
        else:
            buttons.addStretch(1)
            buttons.addWidget(cancel)
        buttons.addWidget(save)
        bl.addLayout(buttons)
        return body

    def _on_save(self):
        time_text = self.time_edit.text().strip().replace(",", ".")
        ics_text = self.ics_edit.text().strip()
        try:
            float(time_text)
            int(ics_text)
        except ValueError:
            QMessageBox.warning(
                self, "Invalid values",
                "Enter a number for both Total testing time and Number of ICs.")
            return
        self.result_time = time_text
        self.result_ics = ics_text
        self.saved = True
        self.accept()

    def _on_delete(self):
        if ConfirmDialog.ask(
            self, "Delete snapshot",
            "Delete this scoreboard snapshot permanently?",
            informative="This action cannot be undone.",
            confirm_text="Yes, delete", destructive=True, subtitle="",
        ):
            self.deleted = True
            self.accept()

    # ---------------------------------------------------- Window dragging
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)


class ExperimentDialog(QDialog):
    """Add / edit a logbook experiment (Delete lives inside, in edit mode).

    Fields come from the manager's column definitions; the Sulfidized synthesis
    extras are shown only for that category. Card-styled, scrollable, no header.
    """

    _NUMERIC = {"test_length_h", "synthesis_time_h", "synthesis_temperature_c"}
    _MULTILINE = {"notes"}
    _DATE = {"experiment_finished_on"}
    _DELETE_STYLE = (
        "QPushButton{background:#F3D9D6;color:#9A2A1E;border:1px solid #E7C6C1;"
        "border-radius:8px;padding:8px 16px;font-weight:600;}"
        " QPushButton:hover{background:#E9C4C0;}"
    )

    def __init__(self, parent=None, *, category="", values=None, adding=False):
        super().__init__(parent)
        self.category = category
        self.adding = adding
        self._values = values or {}
        self.saved = False
        self.deleted = False
        self.result_values = None
        self._editors = {}
        self._build()

    def _fields(self):
        cols = list(STANDARD_COLUMNS)
        if self.category == "Sulfidized":
            cols += list(EXTRA_COLUMNS)
        return cols

    def _build(self):
        self.setWindowTitle("Experiment")
        self.setModal(True)
        self.resize(680, 640)
        self.setMinimumSize(480, 400)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(DIALOG_STYLE + (
            "QFrame#DialogBody { border-top-left-radius: 12px;"
            " border-top-right-radius: 12px; border-top: 1px solid #D8E2E8; }"
        ))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(0)
        card = QFrame()
        card.setObjectName("DialogCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._body(), 1)
        outer.addWidget(card)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(20, 50, 70, 90))
        card.setGraphicsEffect(shadow)

        # Resize handle pinned to the card's bottom-right corner (frameless window
        # has no native border). Positioned manually in resizeEvent.
        self._size_grip = QSizeGrip(self)
        self._size_grip.resize(self._size_grip.sizeHint())
        self._position_size_grip()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_size_grip()

    def _position_size_grip(self) -> None:
        grip = getattr(self, "_size_grip", None)
        if grip is None:
            return
        margin = 20  # matches the outer shadow margin around the card
        grip.move(self.width() - margin - grip.width(),
                  self.height() - margin - grip.height())
        grip.raise_()

    def _body(self) -> QFrame:
        body = QFrame()
        body.setObjectName("DialogBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 20, 24, 18)
        bl.setSpacing(12)

        title = QLabel(("Add" if self.adding else "Edit")
                       + f" experiment, {self.category}")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#1F2A33;"
                            " background:transparent;")
        bl.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        form = QVBoxLayout(content)
        form.setContentsMargins(0, 0, 8, 0)
        form.setSpacing(8)

        num_validator = QRegularExpressionValidator(
            QRegularExpression(r"^\d*[.,]?\d*$"), self)
        for field, header in self._fields():
            row = QHBoxLayout()
            row.setSpacing(12)
            lab = QLabel(header)
            lab.setObjectName("FieldLabel")
            lab.setFixedWidth(160)
            val = self._values.get(field, "") or ""
            multiline = field in self._MULTILINE
            if multiline:
                w = QTextEdit()
                w.setObjectName("CommentsField")
                w.setPlainText(str(val))
                w.setMinimumHeight(70)
                w.setTabChangesFocus(True)
            elif field in self._DATE:
                w = _LogbookDateEdit()
                w.set_from_string(str(val))
            else:
                w = QLineEdit(str(val))
                if field in self._NUMERIC:
                    w.setValidator(num_validator)
            # Center the label against its field so descenders aren't clipped even
            # with a tight row gap; multiline (Notes) keeps its label at the top.
            valign = (Qt.AlignmentFlag.AlignTop if multiline
                      else Qt.AlignmentFlag.AlignVCenter)
            lab.setAlignment(Qt.AlignmentFlag.AlignLeft | valign)
            self._editors[field] = w
            row.addWidget(lab, 0, valign)
            row.addWidget(w, 1)
            form.addLayout(row)

        form.addStretch(1)
        scroll.setWidget(content)
        bl.addWidget(scroll, 1)

        cancel = QPushButton("Cancel")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setDefault(True)
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._on_save)

        # Keep the buttons grouped on the right at any width (Delete, Cancel,
        # Save), so they don't spread apart when the dialog is resized.
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        if not self.adding:
            delete = QPushButton("Delete")
            delete.setStyleSheet(self._DELETE_STYLE)
            delete.setCursor(Qt.CursorShape.PointingHandCursor)
            delete.setAutoDefault(False)
            delete.clicked.connect(self._on_delete)
            buttons.addWidget(delete)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        bl.addLayout(buttons)
        return body

    def _collect(self) -> dict:
        vals = {"category": self.category}
        for field, w in self._editors.items():
            if isinstance(w, _LogbookDateEdit):
                vals[field] = w.date_string()
            elif isinstance(w, QTextEdit):
                vals[field] = w.toPlainText().strip()
            else:
                vals[field] = w.text().strip()
        return vals

    def _on_save(self):
        vals = self._collect()
        if not vals.get("ic_id", "").strip():
            QMessageBox.warning(self, "IC_ID required",
                                "IC_ID is mandatory, please enter one before saving.")
            return
        for f in self._NUMERIC:
            v = vals.get(f, "")
            if v:
                try:
                    float(v.replace(",", "."))
                except ValueError:
                    QMessageBox.warning(self, "Invalid number",
                                        f"'{f}' must be a number or empty.")
                    return
        d = vals.get("experiment_finished_on", "")
        if d:
            try:
                datetime.strptime(d[:10], "%Y-%m-%d")
            except ValueError:
                QMessageBox.warning(self, "Invalid date",
                                    "Experiment finished on must be YYYY-MM-DD or empty.")
                return
        self.result_values = vals
        self.saved = True
        self.accept()

    def _on_delete(self):
        if ConfirmDialog.ask(
            self, "Delete experiment",
            "Delete this experiment permanently?",
            informative="This action cannot be undone.",
            confirm_text="Yes, delete", destructive=True, subtitle="",
        ):
            self.deleted = True
            self.accept()

    # ---------------------------------------------------- Window dragging
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)
