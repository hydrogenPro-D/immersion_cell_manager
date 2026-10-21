"""Experiment planning tab: submit a plan, approve it, schedule it, load it.

"Add new plan" opens the request form; two sub-tabs list the plans:
"Approval pending" (double-click to edit, approve or delete) and "Scheduled"
(drag rows to set the order; double-click to edit or load the plan into a
cell). All writes go through :class:`ExperimentPlanManager`; loading is handed
to the main window, which opens the Cells mapping editor prefilled.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QLineEdit,
    QTextEdit, QComboBox, QDialog, QMessageBox, QInputDialog, QTabWidget,
    QTableWidgetItem, QAbstractItemView, QGraphicsDropShadowEffect,
    QScrollArea, QCompleter, QApplication,
)
from PyQt6.QtCore import Qt, QRegularExpression, pyqtSignal, QEvent, QTimer
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QIcon, QPainter, QPixmap,
    QRegularExpressionValidator,
)

from src.data.experiment_plan_manager import URGENCIES
from src.gui.styles.tab_styles import TAB_STYLE
from src.gui.styles.dialog_styles import DIALOG_STYLE
from src.gui.widgets.confirm_dialog import ConfirmDialog
from src.gui.widgets.side_scroll import SideScroll
from src.gui.widgets.edit_row_dialog import ProjectComboBox
from src.gui.widgets.hover_border_table import (
    HoverBorderTable, HOVER_TABLE_STYLE, TRAILING_ICON_ROLE, fill_columns,
)

# Filter bar: (plan key, label, "all" text). Same look as the Event Log filters.
_FILTERS = [("name", "Name", "All names"), ("protocol", "Protocol", "All protocols"),
            ("project_id", "Project", "All projects"), ("urgency", "Urgency", "All urgencies")]
_FILTER_STYLE = (
    "QComboBox { background:#FFFFFF; border:1px solid #C7D3DB; border-radius:2px;"
    " padding:5px 4px 5px 10px; font-size:13px; color:#000000; }"
    # Typeable: the list opens only from this button, under the drawn arrow
    # (it also keeps the text clear of the arrow, so no right padding).
    " QComboBox::drop-down { width:26px; border:none; }"
    " QComboBox::down-arrow { image:none; }"
    " QComboBox QAbstractItemView { background:#FFFFFF; color:#000000;"
    " selection-background-color:#BFE6E6; selection-color:#000000; }"
)

ANY_CELL = "Any cell"
_PLAN_ID = Qt.ItemDataRole.UserRole

_SUBTAB_STYLE = (
    "QTabWidget::pane { border: 1px solid #E1E8ED; top: -1px; }"
    "QTabBar::tab { padding: 8px 16px; margin-right: 2px; background: #F5F5F5;"
    " color: #1F1F1F; font-weight: 500; border-top-left-radius: 6px;"
    " border-top-right-radius: 6px; }"
    "QTabBar::tab:selected { background: #FFFFFF; color: #3FA3A3;"
    " border-bottom: 2px solid #3FA3A3; }"
    "QTabBar::tab:hover { background: #ECECEC; }"
)
# The dialog look for the inputs, with the app's squarer corners.
_FORM_STYLE = DIALOG_STYLE + (
    "QLabel#FieldLabel { color:#000000; }"
    "QLineEdit, QTextEdit#CommentsField, QComboBox#ProjectField { border-radius: 2px; }"
    "QPushButton { border-radius: 3px; }"
)
_PRIMARY = (
    "QPushButton { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    " stop:0 #55BDBD, stop:1 #3FA3A3); color:#FFFFFF; border:none;"
    " border-radius:3px; padding:9px 18px; font-size:12px; font-weight:700; }"
    " QPushButton:hover { background:#3FA3A3; }"
    " QPushButton:disabled { background:#BCD3D3; color:#EAF4F4; }"
)
_DANGER = (
    "QPushButton { background:#FFFFFF; color:#000000; border:1px solid #E7C2C7;"
    " border-radius:3px; padding:8px 16px; font-weight:600; }"
    " QPushButton:hover { background:#FBEDEF; border-color:#D98A95; }"
)
# Urgency dot color; the text color in the lists (Normal keeps black).
_URGENCY_DOT = {"Low": "#9AA5AE", "Normal": "#3FA3A3", "High": "#E8890C", "Urgent": "#D92D20"}
_URGENCY_TEXT = {"Low": "#6B7A85", "High": "#B35C00", "Urgent": "#B42318"}


def urgency_icon(urgency: str) -> QIcon:
    """A filled colored dot for ``urgency``."""
    pix = QPixmap(12, 12)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(_URGENCY_DOT.get(urgency, "#9AA5AE")))
    painter.drawEllipse(1, 1, 10, 10)
    painter.end()
    return QIcon(pix)


def busy_icon() -> QIcon:
    """Red circle with a white "!": the plan's fixed cell isn't Available."""
    pix = QPixmap(14, 14)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#D92D20"))
    painter.drawEllipse(0, 0, 14, 14)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawRoundedRect(6, 3, 2, 5, 1, 1)  # the "!" stroke
    painter.drawEllipse(6, 9, 2, 2)            # and its dot
    painter.end()
    return QIcon(pix)


def busy_text(channel: str, cell) -> str:
    """Why ``channel`` can't take a plan now, or "" when it is Available."""
    if cell is None:
        return f"Channel {channel} no longer exists."
    status = (cell.get("status") or "").strip()
    if status == "Available":
        return ""
    if status.lower() == "in use":
        return f"Channel {channel} is currently in use."
    return f"Channel {channel} is not available ({status or 'no status'})."


def grip_icon() -> QIcon:
    """Six dots (like the ⠿ grip in Add project): this row can be dragged."""
    pix = QPixmap(10, 16)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#000000"))
    for x in (1, 6):
        for y in (2, 7, 12):
            painter.drawEllipse(x, y, 3, 3)
    painter.end()
    return QIcon(pix)


# ------------------------------------------------------------------ Form fields
class PlanFields(QWidget):
    """The plan's input rows (label left, field right). ``channels`` adds the
    Channel row (approval and schedule only)."""

    def __init__(self, projects: list, protocols: list, channels: list = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_FORM_STYLE)
        self._projects = projects
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.name = QLineEdit()
        self.name.setPlaceholderText("Person requesting the experiment")
        self.test_length = QLineEdit()
        self.test_length.setPlaceholderText("Hours, e.g. 500")
        self.test_length.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"^\d*[.,]?\d*$"), self))
        self.anode = QLineEdit()
        self.cathode = QLineEdit()
        self.protocol = _dropdown(protocols, editable=True)
        self.project = _dropdown(projects, editable=True)
        self.aim = QTextEdit()
        self.aim.setObjectName("CommentsField")
        self.aim.setFixedHeight(64)  # ~3 lines; it scrolls for more
        self.aim.setTabChangesFocus(True)
        self.urgency = _dropdown(URGENCIES, editable=False)
        for i, u in enumerate(URGENCIES):
            self.urgency.setItemIcon(i, urgency_icon(u))
        rows = [("Name", self.name), ("Test length [h]", self.test_length),
                ("Anode", self.anode), ("Cathode", self.cathode),
                ("Protocol", self.protocol), ("Project", self.project),
                ("Aim", self.aim), ("Urgency", self.urgency)]
        self.channel = None
        if channels is not None:
            self.channel = _dropdown([ANY_CELL] + channels, editable=False)
            rows.append(("Channel", self.channel))
        for label, widget in rows:
            lay.addWidget(_form_row(label, widget, top=widget is self.aim))
        self.clear()

    def clear(self) -> None:
        self.set_values({})

    def set_values(self, plan: dict) -> None:
        self.name.setText(plan.get("name", ""))
        self.test_length.setText(plan.get("test_length_h", ""))
        self.anode.setText(plan.get("anode", ""))
        self.cathode.setText(plan.get("cathode", ""))
        for combo, key in ((self.protocol, "protocol"), (self.project, "project_id")):
            combo.setCurrentIndex(-1)
            combo.setEditText(plan.get(key, ""))
        _select(self.urgency, plan.get("urgency") or "Normal")
        self.aim.setPlainText(plan.get("aim", ""))
        if self.channel is not None:
            _select(self.channel, plan.get("channel") or ANY_CELL)

    def values(self) -> dict:
        v = {
            "name": self.name.text().strip(),
            "test_length_h": self.test_length.text().strip(),
            "anode": self.anode.text().strip(),
            "cathode": self.cathode.text().strip(),
            "protocol": self.protocol.currentText().strip(),
            "project_id": self._project_name(self.project.currentText().strip()),
            "aim": self.aim.toPlainText().strip(),
            "urgency": self.urgency.currentText(),
        }
        if self.channel is not None:
            ch = self.channel.currentText()
            v["channel"] = "" if ch == ANY_CELL else ch
        return v

    def _project_name(self, text: str) -> str:
        """The project as spelled in the list ("gen4" -> "Gen4")."""
        return next((p for p in self._projects if p.lower() == text.lower()), text)

    def problem(self) -> str:
        """Why the values can't be saved, or ""."""
        v = self.values()
        if not v["name"]:
            return "Please enter a name."
        if not v["test_length_h"]:
            return "Please enter the test length in hours."
        try:
            float(v["test_length_h"].replace(",", "."))
        except ValueError:
            return "Test length must be a number of hours."
        if v["project_id"] and v["project_id"] not in self._projects:
            return (f"There is no project called '{v['project_id']}'. Choose one from the "
                    "list (projects are added in Cells mapping, Manage projects).")
        return ""


def _dropdown(values: list, editable: bool) -> QComboBox:
    combo = ProjectComboBox()  # combo with a visible arrow
    combo.setObjectName("ProjectField")
    combo.setCursor(Qt.CursorShape.PointingHandCursor)
    combo.addItems(values)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(12)
    if editable:
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        # As you type, the rest of the first match appears selected; Tab keeps it.
        completer = QCompleter(combo.model(), combo)
        completer.setCompletionMode(QCompleter.CompletionMode.InlineCompletion)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        combo.setCompleter(completer)
        # The completion keeps what was typed ("ir-500"); on leaving, use the list's spelling.
        combo.lineEdit().editingFinished.connect(lambda c=combo: _match_case(c))
        # The arrow is an overlay; an editable combo opens only from this button.
        combo.setStyleSheet("QComboBox#ProjectField::drop-down { width: 34px; border: none; }")
        combo.lineEdit().setStyleSheet(
            "background:transparent; border:none; padding:0px;"
            " selection-background-color:#BFE6E6; selection-color:#000000;")
    return combo


def _match_case(combo: QComboBox) -> None:
    text = combo.currentText().strip()
    idx = combo.findText(text, Qt.MatchFlag.MatchFixedString)  # case-insensitive
    if idx >= 0 and combo.itemText(idx) != combo.currentText():
        combo.setEditText(combo.itemText(idx))


def _select(combo: QComboBox, text: str) -> None:
    """Select ``text``, adding it if missing (e.g. a deleted channel)."""
    idx = combo.findText(text)
    if idx < 0:
        combo.addItem(text)
        idx = combo.count() - 1
    combo.setCurrentIndex(idx)


def _form_row(label: str, widget: QWidget, top: bool = False) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(12)
    lab = QLabel(label)
    lab.setObjectName("FieldLabel")
    lab.setFixedWidth(130)
    valign = Qt.AlignmentFlag.AlignTop if top else Qt.AlignmentFlag.AlignVCenter
    lay.addWidget(lab, 0, valign)
    lay.addWidget(widget, 1)
    return row


# ------------------------------------------------------------------ Tables
class ScheduleTable(HoverBorderTable):
    """Rows reorder by dragging, like the Add project column list: the row
    moves live under the cursor (plain mouse events, no Qt drag and drop).
    ``reordered(plan_id)`` fires on release; the owner saves the shown order."""

    reordered = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent, selectable=True)
        self._press_row = -1
        self._press_y = 0.0
        self._row = -1  # where the dragged row is now
        self._dragging = False

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._dragging = False
        self._press_row = -1
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self.indexAt(event.position().toPoint())
            self._press_row = self._row = idx.row() if idx.isValid() else -1
            self._press_y = event.position().y()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)  # hover border
        if self._press_row < 0 or not event.buttons() & Qt.MouseButton.LeftButton:
            # An open hand over the rows says they can be dragged.
            if self.indexAt(event.position().toPoint()).isValid():
                self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.viewport().unsetCursor()
            return
        y = event.position().y()
        if not self._dragging:
            if abs(y - self._press_y) < QApplication.startDragDistance():
                return
            self._dragging = True
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        target = self.rowAt(int(y))
        if target < 0:
            target = 0 if y < 0 else self.rowCount() - 1
        if target != self._row:
            self._move_row(self._row, target)
            self._row = target
        # Scroll along when the cursor nears the top or bottom.
        bar = self.verticalScrollBar()
        if y < 20:
            bar.setValue(bar.value() - 1)
        elif y > self.viewport().height() - 20:
            bar.setValue(bar.value() + 1)

    def mouseReleaseEvent(self, event):
        if not self._dragging:
            super().mouseReleaseEvent(event)  # a plain click (selection toggling)
            self._press_row = -1
            return
        moved = self._row != self._press_row
        self._dragging, self._press_row = False, -1
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()
        if moved:
            self.reordered.emit(self.item(self._row, 0).data(_PLAN_ID))

    def _move_row(self, src: int, dst: int) -> None:
        items = [self.takeItem(src, c) for c in range(self.columnCount())]
        self.removeRow(src)
        self.insertRow(dst)
        for c, item in enumerate(items):
            self.setItem(dst, c, item)
        self.resizeRowToContents(dst)
        self.selectRow(dst)


# ------------------------------------------------------------------ Dialog
class PlanDialog(QDialog):
    """A new plan, or an existing pending / scheduled one. ``action`` tells the
    tab what to do: submit / save / approve / delete / unapprove / load
    (None = cancelled)."""

    def __init__(self, parent, plan: dict, mode: str, projects, protocols, channels=None):
        super().__init__(parent)
        self.plan = plan
        self.action = None
        self.setWindowTitle("Plan")
        self.setModal(True)
        self.resize(640, 570 if mode == "new" else 650)
        self.setStyleSheet(_FORM_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel({"new": "New plan", "pending": "Plan waiting for approval",
                        "scheduled": "Scheduled plan"}[mode])
        title.setStyleSheet("font-size:16px; font-weight:700; color:#000000;")
        root.addWidget(title)
        if mode == "scheduled" and plan.get("approved_by"):
            by = QLabel(f"Approved by {plan['approved_by']}.")
            by.setStyleSheet("font-size:12px; color:#000000;")
            root.addWidget(by)

        self.fields = PlanFields(projects, protocols, None if mode == "new" else channels)
        self.fields.set_values(plan)
        self._initial = self.fields.values()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 8, 0)
        hl.addWidget(self.fields)
        hl.addStretch(1)
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        if mode != "new":
            buttons.addWidget(self._button("Delete", "delete", _DANGER))
        if mode == "scheduled":
            buttons.addWidget(self._button("Back to pending", "unapprove"))
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        if mode != "new":
            buttons.addWidget(self._button("Save", "save"))
        text, action = {"new": ("Submit for approval", "submit"),
                        "pending": ("Save and approve", "approve"),
                        "scheduled": ("Load into cell", "load")}[mode]
        main = self._button(text, action, _PRIMARY)
        main.setDefault(True)
        buttons.addWidget(main)
        root.addLayout(buttons)
        self.fields.name.setFocus()

    def _button(self, text: str, action: str, style: str = None) -> QPushButton:
        b = QPushButton(text)
        b.setAutoDefault(False)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if style:
            b.setStyleSheet(style)
        b.clicked.connect(lambda: self._finish(action))
        return b

    def changed(self) -> bool:
        return self.fields.values() != self._initial

    def _finish(self, action: str) -> None:
        if action != "delete":
            problem = self.fields.problem()
            if problem:
                QMessageBox.warning(self, "Plan", problem)
                return
        self.action = action
        self.accept()

    def reject(self):
        if self.changed() and not ConfirmDialog.ask(
                self, title="Discard changes?", message="Discard your changes to this plan?",
                confirm_text="Discard", cancel_text="Keep editing", destructive=True):
            return
        super().reject()


# ------------------------------------------------------------------ The tab
class ExperimentPlanningTab(QWidget):
    """Add-plan button, approval list and schedule.

    ``protocols()`` gives the protocol suggestions; ``on_load(plan, channel)``
    opens the cell editor prefilled and returns True once the cell was saved
    In use."""

    PENDING, SCHEDULED = 0, 1  # sub-tab indexes

    def __init__(self, manager, cells_manager, protocols=None, on_load=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.cells_manager = cells_manager
        self._protocols = protocols or (lambda: [])
        self.on_load = on_load
        self._approver = ""  # remembered for the next approval in this session
        self._cells = {}  # channel -> cell, read on each refresh (for the busy warning)
        self.init_ui()
        self.refresh()

    # ----------------------------------------------------------------- UI
    def init_ui(self):
        self.setObjectName("TabRoot")
        self.setStyleSheet(TAB_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(12)
        root.addWidget(self._build_header())

        self.missing = QLabel("Experiment planning needs database migration 023. "
                              "Please run it first.")
        self.missing.setStyleSheet("background:#FDE2E0; color:#B42318; padding:10px 14px;"
                                   " font-weight:600;")
        root.addWidget(self.missing)

        bar_host = QWidget()  # scrolls sideways when narrow (keeps the window's minimum width down)
        bar = QHBoxLayout(bar_host)
        bar.setContentsMargins(0, 0, 0, 0)
        self.add_btn = QPushButton("＋  Add new plan")
        self.add_btn.setStyleSheet(_PRIMARY)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.clicked.connect(self._add_plan)
        bar.addWidget(self.add_btn)
        bar.addSpacing(16)
        # Filters apply to both lists.
        self.filters = {}
        for key, label, _all in _FILTERS:
            lab = QLabel(label)
            lab.setStyleSheet("font-size:13px; font-weight:600; color:#000000;")
            combo = ProjectComboBox()  # combo with a visible arrow
            combo.setStyleSheet(_FILTER_STYLE)
            # Only as wide as its longest entry (there are four side by side).
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            combo.setCursor(Qt.CursorShape.PointingHandCursor)
            # Pick a value, or type part of one ("cs" finds Csenger).
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.setCompleter(None)  # inline completion would turn "cs" into one exact name
            combo.lineEdit().setPlaceholderText(_all)
            # Wide enough for the "All ..." text (13 px font) plus padding and the arrow.
            font = QFont(combo.font())
            font.setPixelSize(13)
            combo.setMinimumWidth(QFontMetrics(font).horizontalAdvance(_all) + 52)
            combo.lineEdit().setStyleSheet("background:transparent; border:none; padding:0px;")
            combo.lineEdit().textEdited.connect(lambda _t: self._apply_filters())
            combo.currentIndexChanged.connect(lambda i, c=combo: self._on_filter_picked(c, i))
            combo.installEventFilter(self)  # select all on click, typing replaces
            self.filters[key] = combo
            bar.addWidget(lab)
            bar.addWidget(combo)
        bar.addStretch(1)
        root.addWidget(SideScroll(bar_host))

        self.sub_tabs = QTabWidget()
        self.sub_tabs.setStyleSheet(_SUBTAB_STYLE)
        self.pending_table = HoverBorderTable(selectable=True)
        self.scheduled_table = ScheduleTable()
        self.scheduled_table.reordered.connect(self._on_reordered)
        self.sub_tabs.addTab(self._list_page(
            self.pending_table, "Double-click a plan to edit, approve or delete it."),
            "Approval pending")
        self.sub_tabs.addTab(self._list_page(self.scheduled_table), "Scheduled")
        for table, scheduled in ((self.pending_table, False), (self.scheduled_table, True)):
            self._setup_table(table, scheduled)
        root.addWidget(self.sub_tabs, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("PageHeader")
        header.setFixedHeight(70)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(24, 16, 24, 16)
        title = QLabel("Experiment planning")
        title.setObjectName("PageTitle")
        lay.addWidget(title, 1)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(63, 163, 163, 90))
        header.setGraphicsEffect(shadow)
        return header

    @staticmethod
    def _list_page(table, hint: str = "") -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        if hint:
            lab = QLabel(hint)
            lab.setStyleSheet("font-size:12px; color:#000000;")
            lay.addWidget(lab)
        lay.addWidget(table, 1)
        return page

    _BASE_HEADERS = ["Name", "Test length [h]", "Anode", "Cathode", "Protocol",
                     "Project", "Aim", "Urgency", "Channel"]

    def _setup_table(self, table, scheduled: bool) -> None:
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.setStyleSheet(HOVER_TABLE_STYLE)
        table.horizontalHeader().setFixedHeight(44)
        headers = (["#"] + self._BASE_HEADERS + ["Approved by"] if scheduled
                   else self._BASE_HEADERS + ["Submitted"])
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        if not scheduled:
            table.enable_header_sort()  # the schedule's order is its priority
        table.doubleClicked.connect(
            lambda idx, t=table, s=scheduled: self._open_plan(t, idx.row(), s))

    # --------------------------------------------------------------- Data
    def reload(self) -> None:
        """Re-read the plans (another user changed them)."""
        self.manager.reload()
        self.refresh()

    def refresh(self) -> None:
        self.missing.setVisible(not self.manager.available)
        try:
            self._cells = {c["channel"]: c for c in self.cells_manager.load_all_cells()}
        except Exception:
            pass  # keep the last known statuses
        self.add_btn.setEnabled(self.manager.available)
        self._fill_filters(self.manager.get_pending() + self.manager.get_scheduled())
        self._apply_filters()

    def _apply_filters(self) -> None:
        """Rebuild both lists from the current filters (no re-read)."""
        pending, scheduled = self.manager.get_pending(), self.manager.get_scheduled()
        # "#" is the place in the whole schedule, also when filtered.
        place = {p["id"]: i + 1 for i, p in enumerate(scheduled)}
        for table, plans, index, title, is_sched in (
                (self.pending_table, pending, self.PENDING, "Approval pending", False),
                (self.scheduled_table, scheduled, self.SCHEDULED, "Scheduled", True)):
            shown = [p for p in plans if self._passes(p)]
            self._fill(table, shown, is_sched, place)
            count = f"{len(shown)} of {len(plans)}" if len(shown) != len(plans) else len(plans)
            self.sub_tabs.setTabText(index, f"{title} ({count})")

    def _fill_filters(self, plans: list) -> None:
        """Refill the filters from the plans, keeping the current choices."""
        for key, _label, all_text in _FILTERS:
            if key == "urgency":
                present = {p["urgency"] for p in plans}
                values = [u for u in URGENCIES if u in present]
            else:
                spelled = {}  # lower-case -> first spelling ("Csenger" / "csenger" are one)
                for p in plans:
                    v = p[key].strip()
                    if v:
                        spelled.setdefault(v.lower(), v)
                values = sorted(spelled.values(), key=HoverBorderTable._sort_key)
            combo = self.filters[key]
            picked, typed = self._filter_value(combo)
            text, cursor = combo.currentText(), combo.lineEdit().cursorPosition()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(all_text, None)
            for v in values:
                combo.addItem(v, v.lower())
                if key == "urgency":
                    combo.setItemIcon(combo.count() - 1, urgency_icon(v))
            idx = combo.findData(picked) if picked is not None else -1
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:  # no filter: empty, showing the "All ..." placeholder
                combo.setCurrentIndex(-1)
                if typed:  # keep half-typed text as it was
                    combo.setEditText(text)
                    combo.lineEdit().setCursorPosition(cursor)
            combo.blockSignals(False)

    def _on_filter_picked(self, combo, index: int) -> None:
        if index == 0:  # "All ...": empty the box so the placeholder shows
            combo.blockSignals(True)
            combo.setCurrentIndex(-1)
            combo.blockSignals(False)
        self._apply_filters()

    def eventFilter(self, obj, event):
        # Clicking into a filter selects its text, so typing replaces it.
        # (An editable combo takes the focus itself, not its line edit.)
        if event.type() == QEvent.Type.FocusIn and obj in self.filters.values():
            QTimer.singleShot(0, obj.lineEdit().selectAll)  # after the click placed the cursor
        return super().eventFilter(obj, event)

    @staticmethod
    def _filter_value(combo) -> tuple:
        """(picked value, typed text), both lower-case; (None, "") = no filter.
        A value is "picked" when the text is exactly one of the list's entries."""
        text = combo.currentText().strip()
        idx = combo.findText(text, Qt.MatchFlag.MatchFixedString)  # case-insensitive
        if not text or idx == 0:  # empty or "All ..."
            return None, ""
        if idx > 0 and combo.itemText(idx) == combo.currentText():
            return combo.itemData(idx), ""
        return None, text.lower()

    def _passes(self, plan: dict) -> bool:
        for key, combo in self.filters.items():
            picked, typed = self._filter_value(combo)
            value = plan[key].strip().lower()
            if picked is not None and value != picked:
                return False
            if typed and typed not in value:
                return False
        return True

    def _fill(self, table, plans: list, scheduled: bool, place: dict = None) -> None:
        first = 1 if scheduled else 0  # the "#" column
        table.setRowCount(len(plans))
        for r, p in enumerate(plans):
            aim = p["aim"].splitlines()[0] if p["aim"] else ""
            values = [p["name"], p["test_length_h"], p["anode"], p["cathode"],
                      p["protocol"], p["project_id"], aim[:60] + ("…" if len(aim) > 60 else ""),
                      p["urgency"], p["channel"] or ANY_CELL]
            values = ([str(place.get(p["id"], r + 1))] + values + [p["approved_by"]] if scheduled
                      else values + [p["created_at"][:16]])
            for c, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                if c == 0:
                    item.setData(_PLAN_ID, p["id"])
                    if scheduled:
                        item.setIcon(grip_icon())
                        item.setToolTip("Drag to reorder")
                table.setItem(r, c, item)
            urgency = table.item(r, first + 7)
            urgency.setIcon(urgency_icon(p["urgency"]))
            # Sort by rank, most urgent first on the first click.
            rank = URGENCIES.index(p["urgency"]) if p["urgency"] in URGENCIES else 0
            urgency.setData(HoverBorderTable.SORT_ROLE, -rank)
            if p["urgency"] in _URGENCY_TEXT:
                urgency.setForeground(QColor(_URGENCY_TEXT[p["urgency"]]))
            font = urgency.font()
            font.setBold(p["urgency"] in ("High", "Urgent"))
            urgency.setFont(font)
            if p["aim"]:
                table.item(r, first + 6).setToolTip(p["aim"])
            busy = busy_text(p["channel"], self._cells.get(p["channel"])) if p["channel"] else ""
            if busy:
                channel = table.item(r, first + 8)
                channel.setData(TRAILING_ICON_ROLE, busy_icon())  # after the number
                channel.setToolTip(busy)
        if not scheduled:
            table.apply_sort()
        fill_columns(table)
        table.resizeRowsToContents()

    def _projects(self) -> list:
        pm = self.cells_manager.get_projects_manager()
        return sorted(pm.get_projects(), key=str.casefold)

    def _channels(self) -> list:
        return [c["channel"] for c in self.cells_manager.load_all_cells() if c.get("channel")]

    def _all_protocols(self) -> list:
        seen, out = set(), []
        for p in self.manager.get_recent_values("protocol") + list(self._protocols()):
            if p.lower() not in seen:
                seen.add(p.lower())
                out.append(p)
        return out

    # ------------------------------------------------------------ New plan
    def _add_plan(self) -> None:
        dlg = PlanDialog(self, {}, "new", self._projects(), self._all_protocols())
        dlg.exec()
        if dlg.action != "submit":
            return
        error = self.manager.add_plan(dlg.fields.values())
        self._report(error)
        if not error:
            self.sub_tabs.setCurrentIndex(self.PENDING)

    # ------------------------------------------------------- Edit / approve
    def _open_plan(self, table, row: int, scheduled: bool) -> None:
        item = table.item(row, 0)
        plan = self.manager.get_plan(item.data(_PLAN_ID) if item else None)
        if plan is None:
            QMessageBox.information(self, "Plan not found",
                                    "This plan no longer exists (someone else changed it).")
            self.reload()
            return
        dlg = PlanDialog(self, plan, "scheduled" if scheduled else "pending",
                         self._projects(), self._all_protocols(), self._channels())
        dlg.exec()
        if dlg.action is None:
            return
        values, pid = dlg.fields.values(), plan["id"]
        if dlg.action == "delete":
            if ConfirmDialog.ask(self, title="Delete plan",
                                 message=f"Delete the plan requested by <b>{plan['name']}</b>?",
                                 confirm_text="Yes, delete", cancel_text="Cancel",
                                 destructive=True):
                self._report(self.manager.delete(pid))
            return
        if dlg.action == "approve":
            name, ok = QInputDialog.getText(self, "Approve plan", "Approved by:",
                                            text=self._approver)
            if not ok or not name.strip():
                return
            self._approver = name.strip()
        # Save the edits first, then the action itself.
        error = self.manager.update_plan(pid, values) if dlg.changed() else ""
        if not error and dlg.action == "approve":
            error = self.manager.approve(pid, self._approver)
        elif not error and dlg.action == "unapprove":
            error = self.manager.unapprove(pid)
        self._report(error)
        if not error and dlg.action == "load":
            self._load(self.manager.get_plan(pid) or {**plan, **values})

    def _report(self, error: str) -> None:
        self.refresh()
        if error:
            QMessageBox.warning(self, "Not saved", error)

    # ------------------------------------------------------------- Schedule
    def _on_reordered(self, moved_id) -> None:
        """Save the order the rows were dragged into."""
        t = self.scheduled_table
        shown = [t.item(r, 0).data(_PLAN_ID) for r in range(t.rowCount())]
        # Filtered: the shown plans swap places among their own slots in the
        # whole schedule; hidden plans keep theirs.
        full = [p["id"] for p in self.manager.get_scheduled()]
        slots = sorted(full.index(pid) for pid in shown if pid in full)
        for slot, pid in zip(slots, shown):
            full[slot] = pid
        self._report(self.manager.reorder(full))
        row = next((r for r in range(t.rowCount())
                    if t.item(r, 0).data(_PLAN_ID) == moved_id), -1)
        if row >= 0:
            t.selectRow(row)

    def _load(self, plan: dict) -> None:
        """Load into the plan's cell if Available, or into an Available cell
        the user picks ("Any cell")."""
        cells = {c["channel"]: c for c in self.cells_manager.load_all_cells()}
        channel = plan.get("channel", "")
        busy = busy_text(channel, cells.get(channel)) if channel else ""
        if busy:
            # The planned cell is taken: say so, then let them pick another one.
            QMessageBox.warning(self, "Cell busy",
                                f"{busy}\nChoose another cell that is Available.")
            channel = ""
        if not channel:
            free = [ch for ch, c in cells.items() if c.get("status") == "Available"]
            if not free:
                QMessageBox.information(self, "No free cell", "No cell is Available right now.")
                return
            channel, ok = QInputDialog.getItem(self, "Load plan", "Load into Available cell:",
                                               free, 0, False)
            if not ok:
                return
        if self.on_load is None or not self.on_load(plan, channel):
            return  # cancelled or not saved: the plan stays scheduled
        error = self.manager.mark_started(plan["id"], channel)
        self.refresh()
        if error:
            QMessageBox.warning(self, "Plan not updated",
                                f"Channel {channel} was saved, but the plan could not be marked "
                                f"as started, so it is still listed.\n\n{error}")
