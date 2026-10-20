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
    QMessageBox, QTextEdit, QSizeGrip, QComboBox,
)
from PyQt6.QtCore import Qt, QRegularExpression, QTimer, QDate, QEvent
from PyQt6.QtGui import QColor, QRegularExpressionValidator

from src.gui.styles.tab_styles import TAB_STYLE
from src.gui.styles.dialog_styles import DIALOG_STYLE
from src.gui.widgets.confirm_dialog import ConfirmDialog
from src.gui.widgets.edit_row_dialog import CalendarDateEdit, ProjectComboBox
from src.gui.widgets.hover_border_table import HoverBorderTable, HOVER_TABLE_STYLE
from src.data.logbook_manager import STANDARD_COLUMNS, BUILTIN_TYPES
from src.gui.widgets.logbook_project_dialog import ManageProjectsDialog, ProjectDialog

_SUBTAB_STYLE = (
    "QTabWidget::pane { border: 1px solid #E1E8ED; top: -1px; }"
    "QTabBar::tab { padding: 8px 16px; margin-right: 2px; background: #F5F5F5;"
    " color: #1F1F1F; font-weight: 500; border-top-left-radius: 6px;"
    " border-top-right-radius: 6px; }"
    "QTabBar::tab:selected { background: #FFFFFF; color: #3FA3A3;"
    " border-bottom: 2px solid #3FA3A3; }"
    "QTabBar::tab:hover { background: #ECECEC; }"
)

# Secondary button. Enabled: teal-tinted with a teal border so it clearly reads
# as active; disabled: flat, borderless grey so the state change is obvious.
_SECONDARY_BTN = (
    "QPushButton { background:#E4F2F2; color:#1A5E5E; border:1px solid #6FBFBF;"
    " border-radius:3px; padding:9px 20px; font-size:12px; font-weight:700;"
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
        self.setObjectName("DateField")  # match the other input fields' styling
        self.setDisplayFormat("yyyy-MM-dd")
        self.setMinimumDate(self.UNSET)
        self.setSpecialValueText("not set")
        self.setDate(self.UNSET)
        self.calendarWidget().installEventFilter(self)  # open on current month

    def is_set(self) -> bool:
        return self.date() != self.UNSET

    def clear_date(self) -> None:
        self.setDate(self.UNSET)

    def date_string(self) -> str:
        return self.date().toString("yyyy-MM-dd") if self.is_set() else ""

    def set_from_string(self, text: str) -> None:
        d = QDate.fromString((text or "")[:10], "yyyy-MM-dd")
        self.setDate(d if d.isValid() else self.UNSET)

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


# Fields whose earlier values are offered in a dropdown (typing still allowed).
_SUGGESTED_FIELDS = ("protocol", "format", "archived_in")


def logbook_suggestions(manager):
    """Callable: project -> {field: values}, most recent first. A field the
    project has no values for yet falls back to the whole logbook's."""
    def suggest(category=None):
        return {f: (manager.get_recent_values(f, category) if category else [])
                or manager.get_recent_values(f)
                for f in _SUGGESTED_FIELDS}
    return suggest


def logbook_columns(manager):
    """Callable: project -> [(field, label, type)] for ExperimentDialog."""
    def columns(category):
        types = manager.get_column_types(category)
        return [(f, label, types.get(f, "text")) for f, label in manager.get_columns(category)]
    return columns


def _choose_project(parent, projects: list, current: str):
    """Ask which project to move an experiment to; the name, or None."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Move to other project")
    dlg.setModal(True)
    dlg.setMinimumWidth(440)
    dlg.setStyleSheet(DIALOG_STYLE + "QLabel#FieldLabel { color:#000000; }")
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(22, 20, 22, 18)
    lay.setSpacing(10)
    title = QLabel("Move to other project")
    title.setStyleSheet("font-size:16px; font-weight:700; color:#000000;")
    lay.addWidget(title)
    lay.addWidget(QLabel(f"Move this experiment from <b>{current}</b> to:"))
    combo = ExperimentDialog._dropdown([p for p in projects if p != current], editable=False)
    combo.setPlaceholderText("Choose a project")
    combo.setCurrentIndex(-1)
    lay.addWidget(combo)
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    cancel = QPushButton("Cancel")
    cancel.setAutoDefault(False)
    cancel.clicked.connect(dlg.reject)
    move = QPushButton("Move")
    move.setEnabled(False)
    move.clicked.connect(dlg.accept)
    combo.currentIndexChanged.connect(lambda i: move.setEnabled(i >= 0))
    buttons.addWidget(cancel)
    buttons.addWidget(move)
    lay.addLayout(buttons)
    if dlg.exec() != QDialog.DialogCode.Accepted or combo.currentIndex() < 0:
        return None
    return combo.currentText()


def offer_logbook_entry(parent, manager, prefill: dict, channel: str = "",
                        can_go_back: bool = False):
    """Offer to add a just-finished experiment to the logbook. ``prefill`` holds
    the fields known from Cells mapping; ``can_go_back`` adds a "Go back" button.

    Returns (outcome, sub-tab): ("added", category), ("skipped", None) or
    ("back", None) when the user wants the status change undone.
    """
    dlg = ExperimentDialog(
        parent, values=prefill, adding=True,
        categories=manager.get_categories(),
        suggestions=logbook_suggestions(manager),
        columns=logbook_columns(manager),
        title="Add to IC Logbook",
        intro=(f"Channel {channel} is no longer in use. Choose the project and "
               "complete the details; fields known from Cells mapping are filled in."),
        confirm_text="Add to logbook", cancel_text="Skip", confirm_skip=True,
        back_text="Go back" if can_go_back else None)
    dlg.exec()
    if dlg.went_back:
        return "back", None
    if not dlg.saved:
        return "skipped", None
    if not manager.add_experiment(dlg.category, dlg.result_values):
        QMessageBox.warning(parent, "Not added",
                            "The experiment could not be added to the IC Logbook.")
        return "skipped", None
    return "added", dlg.category


# Experiment id stored on each row's first cell (rows must not be found by position).
_EXP_ID = Qt.ItemDataRole.UserRole


def _warn_not_saved(parent) -> None:
    QMessageBox.warning(
        parent, "Not saved",
        "The change could not be saved to the database (connection problem or "
        "another user's change). The table shows what is stored now.")


class _PendingTable(QWidget):
    """Stand-in for a project table that is built the first time it's opened."""


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
        self.add_project_btn = QPushButton("＋  Add project")
        self.add_project_btn.setStyleSheet(_SECONDARY_BTN)
        self.add_project_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_project_btn.clicked.connect(self._on_add_project)
        toolbar.addWidget(self.add_project_btn)
        self.manage_projects_btn = QPushButton("Manage projects")
        self.manage_projects_btn.setStyleSheet(_SECONDARY_BTN)
        self.manage_projects_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manage_projects_btn.clicked.connect(self._on_manage_projects)
        toolbar.addWidget(self.manage_projects_btn)
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
        # Keep their space when hidden so the sub-tab bar doesn't jump on Summary.
        for btn in (self.update_btn, self.add_btn):
            policy = btn.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            btn.setSizePolicy(policy)
        toolbar.addWidget(self.update_btn)
        toolbar.addWidget(self.add_btn)
        root.addLayout(toolbar)

        self.sub_tabs = QTabWidget()
        self.sub_tabs.setStyleSheet(_SUBTAB_STYLE)
        self.sub_tabs.setUsesScrollButtons(True)
        self.sub_tabs.currentChanged.connect(self._on_sub_tab_changed)
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
        # Project tables are built on first open: all ~1,900 rows up front made
        # the first click on the IC Logbook lag (~0.7 s).
        self.sub_tabs.blockSignals(True)
        self.sub_tabs.clear()
        self.sub_tabs.addTab(self._build_summary(), "Summary")
        for category in self.manager.get_categories():
            self.sub_tabs.addTab(_PendingTable(), category)
        self.sub_tabs.blockSignals(False)
        self._on_sub_tab_changed(self.sub_tabs.currentIndex())

    def _on_sub_tab_changed(self, index: int) -> None:
        if isinstance(self.sub_tabs.widget(index), _PendingTable):
            self._swap_tab(index, self._build_category(self.sub_tabs.tabText(index)))
        self._sync_toolbar()

    def _swap_tab(self, index: int, widget: QWidget) -> None:
        """Replace the widget of tab ``index``, keeping the open tab."""
        old, text, current = self.sub_tabs.widget(index), self.sub_tabs.tabText(index), \
            self.sub_tabs.currentIndex()
        self.sub_tabs.blockSignals(True)  # the swap would re-enter the change slot
        self.sub_tabs.removeTab(index)
        self.sub_tabs.insertTab(index, widget, text)
        self.sub_tabs.setCurrentIndex(current)
        self.sub_tabs.blockSignals(False)
        old.deleteLater()

    # --------------------------------------------------------- Category tab
    def _make_table(self, selectable: bool = False) -> QTableWidget:
        table = HoverBorderTable(selectable=selectable)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(True)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        table.setStyleSheet(HOVER_TABLE_STYLE)
        table.horizontalHeader().setFixedHeight(44)
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
            num.setData(_EXP_ID, exp.get("id"))  # edits find the row by id, not position
            table.setItem(r, 0, num)
            for c, (field, _) in enumerate(cols):
                text = (exp.get(field) or "").strip()
                if field == "ic_id":
                    text = " ".join(text.split())  # IC_ID stays on one line
                item = QTableWidgetItem(text)
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
        # IC_ID is exempt from the cap: always wide enough for the longest ID.
        for c, (field, _) in enumerate(cols):
            if field == "ic_id":
                fm = table.fontMetrics()
                longest = max((fm.horizontalAdvance(table.item(r, c + 1).text())
                               for r in range(table.rowCount())), default=0)
                table.setColumnWidth(c + 1, max(240, longest + 28))
        table.resizeRowsToContents()
        # Double-click a row to edit it; selection drives the global Update button.
        table.doubleClicked.connect(
            lambda idx, c=category, t=table: self._edit_experiment(c, t, idx.row()))
        table.selectionModel().selectionChanged.connect(
            lambda *_a: self._sync_toolbar())
        # Start scrolled to the newest (bottom) rows.
        QTimer.singleShot(0, table.scrollToBottom)
        return table

    # --------------------------------------------------------- Global toolbar
    def _current_category(self):
        """(category, table) for the open category tab, or (None, None)."""
        w = self.sub_tabs.currentWidget()
        if isinstance(w, HoverBorderTable) and getattr(w, "_selectable", False):
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
            self._edit_experiment(category, table, table.selected_row())

    # ------------------------------------------------------ Experiment edits
    def _refresh_category(self, category: str) -> None:
        """Reload from the DB and rebuild the Summary + this category tab."""
        self._refresh_categories([category], select=category)

    def _refresh_categories(self, categories: list, select: str) -> None:
        """Rebuild the Summary and these category tabs (adding any that are new,
        e.g. a just-created project), then open ``select``. The manager has
        already re-read the data (every write does)."""
        self._swap_tab(0, self._build_summary())
        for category in categories:
            index = next((i for i in range(self.sub_tabs.count())
                          if self.sub_tabs.tabText(i) == category), None)
            if index is None:
                self.sub_tabs.addTab(_PendingTable(), category)
            elif not isinstance(self.sub_tabs.widget(index), _PendingTable):
                # Built before: rebuild. Unopened ones read fresh data when opened.
                self._swap_tab(index, self._build_category(category))
        self.sub_tabs.blockSignals(True)
        for i in range(self.sub_tabs.count()):
            if self.sub_tabs.tabText(i) == select:
                self.sub_tabs.setCurrentIndex(i)
        self.sub_tabs.blockSignals(False)
        self._on_sub_tab_changed(self.sub_tabs.currentIndex())

    def _on_manage_projects(self) -> None:
        if not self.manager.can_archive():
            QMessageBox.information(
                self, "Not available yet",
                "Archiving projects needs database migration 021. Please run it first.")
            return
        dlg = ManageProjectsDialog(self, self.manager)
        dlg.exec()
        if dlg.saved:
            # Archived projects lose their tab; stay on the open one if still active.
            current = self.sub_tabs.tabText(self.sub_tabs.currentIndex())
            self._populate_sub_tabs()
            for i in range(self.sub_tabs.count()):
                if self.sub_tabs.tabText(i) == current:
                    self.sub_tabs.setCurrentIndex(i)
            self._sync_toolbar()

    def _on_add_project(self) -> None:
        if not self.manager.has_projects():
            QMessageBox.information(
                self, "Not available yet",
                "Adding projects needs database migration 020. Please run it first.")
            return
        dlg = ProjectDialog(self, self.manager)
        dlg.exec()
        if dlg.created:
            self._refresh_categories([dlg.created], select=dlg.created)

    def show_added(self, category: str) -> None:
        """Refresh after an entry was added from outside (Cells mapping)."""
        self._refresh_category(category)

    def _add_experiment(self, category: str) -> None:
        dlg = ExperimentDialog(self, category=category, values={}, adding=True,
                               suggestions=logbook_suggestions(self.manager),
                               columns=logbook_columns(self.manager))
        dlg.exec()
        if dlg.saved:
            if not self.manager.add_experiment(category, dlg.result_values):
                _warn_not_saved(self)
            self._refresh_category(category)

    def _edit_experiment(self, category: str, table, row: int) -> None:
        item = table.item(row, 0)
        exp = self.manager.get_experiment(item.data(_EXP_ID) if item else None)
        if exp is None:
            QMessageBox.information(
                self, "Experiment not found",
                "This experiment no longer exists (another user may have changed "
                "it). The table has been refreshed.")
            self.manager.reload()
            self._refresh_category(category)
            return
        dlg = ExperimentDialog(self, category=category, values=exp, adding=False,
                               suggestions=logbook_suggestions(self.manager),
                               columns=logbook_columns(self.manager),
                               move_targets=self.manager.get_categories())
        dlg.exec()
        if dlg.moved_to:
            ok = self.manager.move_experiment(exp.get("id"), dlg.moved_to, dlg.result_values)
            self._refresh_categories([category, dlg.moved_to], select=dlg.moved_to)
        elif dlg.deleted:
            ok = self.manager.delete_experiment(exp.get("id"))
            self._refresh_category(category)
        elif dlg.saved:
            ok = self.manager.update_experiment(exp.get("id"), dlg.result_values)
            self._refresh_category(category)
        else:
            return
        if not ok:
            _warn_not_saved(self)

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

        # Per-category breakdown, active projects first.
        layout.addWidget(self._section_label("Active projects"))
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

        # Archived projects: their history, apart from the active ones.
        archived = data.get("per_category_archived") or []
        if archived:
            layout.addWidget(self._section_label("Archived projects"))
            arch_table = self._make_table()
            arch_table.setColumnCount(3)
            arch_table.setHorizontalHeaderLabels(
                ["Category", "Number of ICs", "Total testing time [h]"])
            arch_table.setRowCount(len(archived))
            for r, row in enumerate(archived):
                arch_table.setItem(r, 0, QTableWidgetItem(row["category"]))
                self._num_cell(arch_table, r, 1, f"{row['count']:,}")
                self._num_cell(arch_table, r, 2, f"{row['hours']:,.1f}")
            arch_table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.Stretch)
            arch_table.resizeRowsToContents()
            arch_table.setMinimumHeight(min(60 + 30 * len(archived), 400))
            layout.addWidget(arch_table)

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
        self._swap_tab(0, self._build_summary())

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
            ok = self.manager.delete_scoreboard(row)
        elif dlg.saved:
            ok = self.manager.update_scoreboard(row, dlg.result_time, dlg.result_ics)
        else:
            return
        self._refresh_summary()
        if not ok:
            _warn_not_saved(self)

    def _add_scoreboard(self) -> None:
        dlg = ScoreboardDialog(self, adding=True)
        dlg.exec()
        if dlg.saved:
            ok = self.manager.add_scoreboard(dlg.result_time, dlg.result_ics)
            self._refresh_summary()
            if not ok:
                _warn_not_saved(self)

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
            " border-radius:0px; }")
        lay = QVBoxLayout(chip)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(2)
        v = QLabel(value)
        v.setStyleSheet("font-size:18px; font-weight:700; color:#000000; border:none;"
                        " background:transparent;")
        k = QLabel(label)
        k.setStyleSheet("font-size:11px; color:#000000; border:none;"
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
        """Re-read the database (another user changed it) and rebuild what is
        built, keeping the open tab."""
        self.manager.reload()
        self.refresh()

    def refresh(self) -> None:
        current = self.sub_tabs.tabText(self.sub_tabs.currentIndex())
        tabs = [self.sub_tabs.tabText(i) for i in range(1, self.sub_tabs.count())]
        if tabs != self.manager.get_categories():
            self._populate_sub_tabs()  # projects added, renamed or archived
            for i in range(self.sub_tabs.count()):
                if self.sub_tabs.tabText(i) == current:
                    self.sub_tabs.setCurrentIndex(i)
            self._sync_toolbar()
            return
        self._swap_tab(0, self._build_summary())
        for i, category in enumerate(tabs, start=1):
            if not isinstance(self.sub_tabs.widget(i), _PendingTable):
                self._swap_tab(i, self._build_category(category))
        self._sync_toolbar()


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
            "QFrame#DialogBody { border-top-left-radius: 6px;"
            " border-top-right-radius: 6px; border-top: 1px solid #D8E2E8; }"
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
    """Add / edit a logbook experiment (Delete and Move live inside, in edit mode).

    Fields follow the project's columns (``columns``: callable project ->
    [(field, label, type)]), rebuilt when a different project is picked.
    Card-styled, scrollable, no header.
    """

    _MULTILINE = {"notes"}
    _DELETE_STYLE = (
        "QPushButton{background:#F3D9D6;color:#9A2A1E;border:1px solid #E7C6C1;"
        "border-radius:8px;padding:8px 16px;font-weight:600;}"
        " QPushButton:hover{background:#E9C4C0;}"
    )

    def __init__(self, parent=None, *, category="", values=None, adding=False,
                 categories=None, suggestions=None, title=None, intro="",
                 confirm_text="Save", cancel_text="Cancel", confirm_skip=False,
                 back_text=None, columns=None, move_targets=None):
        """``categories``: show a required Project (sub-tab) picker (starts empty) instead
        of a fixed ``category``. ``suggestions``: callable project ->
        {field: [values]}; those fields become dropdowns that still accept
        typing, refilled whenever the project changes. ``move_targets``: other
        projects, shows "Move to other project" (edit mode)."""
        super().__init__(parent)
        self.category = category
        self.adding = adding
        self._values = dict(values or {})  # also caches typed values across rebuilds
        self._columns = columns
        self._move_targets = move_targets or []
        self.moved_to = None
        self._categories = categories
        self._suggest = suggestions
        self._suggestions = suggestions(category or None) if suggestions else {}
        self._title = title
        self._intro = intro
        self._confirm_text = confirm_text
        self._cancel_text = cancel_text
        self._confirm_skip = confirm_skip  # ask before Skip / Escape / close
        self._back_text = back_text  # optional extra button that undoes the change
        self.went_back = False
        self.saved = False
        self.deleted = False
        self.result_values = None
        self._editors = {}
        self._labels = {}
        self._types = {}
        self._build()

    def _fields(self):
        """[(field, label, type)] for the current project (the standard columns
        until one is picked)."""
        if self._columns and self.category:
            return self._columns(self.category)
        return [(f, label, BUILTIN_TYPES.get(f, "text")) for f, label in STANDARD_COLUMNS]

    def _on_category_chosen(self, text: str) -> None:
        self._values.update(self._collect())  # keep what was typed so far
        self.category = text
        self._build_fields()
        self._refill_suggestions()

    def _refill_suggestions(self) -> None:
        """Offer the chosen project's earlier values; keep whatever was typed."""
        if not self._suggest:
            return
        for field, values in self._suggest(self.category or None).items():
            combo = self._editors.get(field)
            if not isinstance(combo, QComboBox):
                continue
            text = combo.currentText()
            combo.clear()
            combo.addItems(values)
            combo.setCurrentIndex(-1)
            combo.setEditText(text)
            self._fit_popup(combo)

    def _build(self):
        self.setWindowTitle("Experiment")
        self.setModal(True)
        self.resize(680, 640)
        self.setMinimumSize(480, 400)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(DIALOG_STYLE + (
            "QFrame#DialogBody { border-top-left-radius: 6px;"
            " border-top-right-radius: 6px; border-top: 1px solid #D8E2E8; }"
            # Squarer inputs than the shared 5 px.
            "QLineEdit, QTextEdit#CommentsField, QComboBox#ProjectField,"
            " QDateEdit#DateField { border-radius: 2px; }"
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

        title = QLabel(self._title or (("Add" if self.adding else "Edit")
                                       + f" experiment, {self.category}"))
        title.setStyleSheet("font-size:16px; font-weight:700; color:#1F2A33;"
                            " background:transparent;")
        bl.addWidget(title)
        if self._intro:
            intro = QLabel(self._intro)
            intro.setWordWrap(True)
            intro.setStyleSheet("font-size:12px; color:#000000; background:transparent;")
            bl.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        form = QVBoxLayout(content)
        form.setContentsMargins(0, 0, 8, 0)
        form.setSpacing(8)

        if self._categories is not None:
            self.category_combo = self._dropdown(self._categories, editable=False)
            self.category_combo.setPlaceholderText("Choose a project")
            self.category_combo.setCurrentIndex(-1)
            self.category_combo.currentTextChanged.connect(self._on_category_chosen)
            # The key choice in this form: thicker teal border, bold label.
            # Padding is 1 px less so the field keeps the same height.
            self.category_combo.setStyleSheet(
                "QComboBox#ProjectField { border:2px solid #3FA3A3; background:#FFFFFF;"
                " padding:7px 11px; padding-right:33px; font-weight:600; }")
            project_row = self._form_row("Project", self.category_combo)
            project_row.findChild(QLabel, "FieldLabel").setStyleSheet(
                "font-weight:700; color:#000000;")
            form.addWidget(project_row)

        self._fields_box = QVBoxLayout()
        self._fields_box.setContentsMargins(0, 0, 0, 0)
        self._fields_box.setSpacing(8)
        form.addLayout(self._fields_box)
        self._build_fields()

        form.addStretch(1)
        scroll.setWidget(content)
        bl.addWidget(scroll, 1)

        cancel = QPushButton(self._cancel_text)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        save = QPushButton(self._confirm_text)
        save.setDefault(True)
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._on_save)

        # Keep the buttons grouped on the right at any width (Delete, Cancel,
        # Save), so they don't spread apart when the dialog is resized.
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        if not self.adding and self._move_targets:
            move = QPushButton("Move to other project")
            move.setCursor(Qt.CursorShape.PointingHandCursor)
            move.setAutoDefault(False)
            move.clicked.connect(self._on_move)
            buttons.addWidget(move)
        if not self.adding:
            delete = QPushButton("Delete")
            delete.setStyleSheet(self._DELETE_STYLE)
            delete.setCursor(Qt.CursorShape.PointingHandCursor)
            delete.setAutoDefault(False)
            delete.clicked.connect(self._on_delete)
            buttons.addWidget(delete)
        if self._back_text:
            back = QPushButton(self._back_text)
            back.setCursor(Qt.CursorShape.PointingHandCursor)
            back.setAutoDefault(False)
            back.clicked.connect(self._on_back)
            buttons.addWidget(back)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        bl.addLayout(buttons)
        return body

    def _build_fields(self) -> None:
        """(Re)build the field rows for the current project's columns."""
        while self._fields_box.count():
            item = self._fields_box.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._editors, self._labels, self._types = {}, {}, {}
        num_validator = QRegularExpressionValidator(
            QRegularExpression(r"^-?\d*[.,]?\d*$"), self)
        for field, label, ftype in self._fields():
            val = str(self._values.get(field, "") or "")
            multiline = field in self._MULTILINE
            if multiline:
                w = QTextEdit()
                w.setObjectName("CommentsField")
                w.setPlainText(val)
                w.setMinimumHeight(70)
                w.setTabChangesFocus(True)
            elif ftype == "date":
                w = _LogbookDateEdit()
                w.set_from_string(val)
            elif field in self._suggestions:
                w = self._dropdown(self._suggestions[field], editable=True)
                w.setCurrentIndex(-1)
                w.setEditText(val)
            else:
                w = QLineEdit(val)
                if ftype == "number":
                    w.setValidator(num_validator)
            self._editors[field] = w
            self._labels[field] = label
            self._types[field] = ftype
            self._fields_box.addWidget(self._form_row(label, w, top=multiline))

    def _on_move(self):
        target = _choose_project(self, self._move_targets, self.category)
        if not target:
            return
        vals = self._validated()
        if vals is None:
            return
        self.result_values = vals
        self.moved_to = target
        self.saved = True
        self.accept()

    def _on_back(self):
        self.went_back = True
        QDialog.reject(self)  # not self.reject(): that asks about skipping

    @staticmethod
    def _form_row(label: str, widget: QWidget, top: bool = False) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lab = QLabel(label)
        lab.setObjectName("FieldLabel")
        lab.setFixedWidth(160)
        # Center the label against its field so descenders aren't clipped even
        # with a tight row gap; multiline (Notes) keeps its label at the top.
        valign = Qt.AlignmentFlag.AlignTop if top else Qt.AlignmentFlag.AlignVCenter
        lab.setAlignment(Qt.AlignmentFlag.AlignLeft | valign)
        lay.addWidget(lab, 0, valign)
        lay.addWidget(widget, 1)
        return row

    @staticmethod
    def _dropdown(values: list, editable: bool) -> QComboBox:
        combo = ProjectComboBox()  # combo with a visible arrow
        combo.setObjectName("ProjectField")
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        combo.addItems(values)
        # Don't widen to the longest entry (some are ~100 chars): that pushed the
        # form wider than the window and hid the arrows. The open list still
        # gets room to show long values.
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
        ExperimentDialog._fit_popup(combo)
        if editable:
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            # The shared style shrinks the drop-down button to 0 px (the arrow is
            # an overlay). An editable combo only opens from that button, so give
            # it back a hit area under the arrow; the text part stays typeable.
            combo.setStyleSheet(
                "QComboBox#ProjectField::drop-down { width: 34px; border: none; }")
            # The dialog's QLineEdit style would draw a second box inside the combo.
            combo.lineEdit().setStyleSheet(
                "background:transparent; border:none; padding:0px;")
        return combo

    @staticmethod
    def _fit_popup(combo: QComboBox) -> None:
        combo.view().setMinimumWidth(min(combo.view().sizeHintForColumn(0) + 30, 760))

    def _collect(self) -> dict:
        vals = {"category": self.category}
        for field, w in self._editors.items():
            if isinstance(w, _LogbookDateEdit):
                vals[field] = w.date_string()
            elif isinstance(w, QTextEdit):
                vals[field] = w.toPlainText().strip()
            elif isinstance(w, QComboBox):
                vals[field] = w.currentText().strip()
            else:
                vals[field] = w.text().strip()
        return vals

    def _validated(self):
        """The form's values, or None (after a warning) if something is off."""
        if self._categories is not None and not self.category:
            QMessageBox.warning(self, "Project required",
                                "Please choose the project to add it to.")
            return None
        vals = self._collect()
        if not vals.get("ic_id", "").strip():
            QMessageBox.warning(self, "IC_ID required",
                                "IC_ID is mandatory, please enter one before saving.")
            return None
        for f, ftype in self._types.items():
            v = vals.get(f, "")
            if v and ftype == "number":
                try:
                    float(v.replace(",", "."))
                except ValueError:
                    QMessageBox.warning(self, "Invalid number",
                                        f"'{self._labels[f]}' must be a number or empty.")
                    return None
            elif v and ftype == "date":
                try:
                    datetime.strptime(v[:10], "%Y-%m-%d")
                except ValueError:
                    QMessageBox.warning(self, "Invalid date",
                                        f"'{self._labels[f]}' must be YYYY-MM-DD or empty.")
                    return None
        return vals

    def _on_save(self):
        vals = self._validated()
        if vals is None:
            return
        self.result_values = vals
        self.saved = True
        self.accept()

    def reject(self):
        # Skip, Escape and closing all land here; make skipping a deliberate choice.
        if self._confirm_skip and not ConfirmDialog.ask(
                self, title="Skip the IC Logbook?",
                message="This experiment will <b>not</b> be added to the IC Logbook.",
                informative="It can only be added later by hand.",
                confirm_text="Yes, skip", cancel_text="Keep editing", destructive=True):
            return
        super().reject()

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
