"""One project's history: experiments running now, planned experiments, past experiments."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidgetItem,
    QAbstractItemView, QScrollArea, QFrame, QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from src.data.project_history import ProjectHistory
from src.gui.styles.dialog_styles import DIALOG_STYLE
from src.gui.widgets.hover_border_table import HoverBorderTable, HOVER_TABLE_STYLE, fill_columns

_TEXT = QColor("#1F2A33")
_CLOSE_BTN = (
    "QPushButton { background:#EBEFF2; color:#000000; border:none; min-width:0px;"
    " border-radius:3px; padding:9px 18px; font-size:12px; font-weight:600; }"
    " QPushButton:hover { background:#DCE3E8; }"
)
_HEADER_H = 40
_MAX_ROWS = 12  # taller sections scroll inside their table


def _table(headers: list, rows: list) -> HoverBorderTable:
    table = HoverBorderTable()
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    table.setStyleSheet(HOVER_TABLE_STYLE)
    table.horizontalHeader().setFixedHeight(_HEADER_H)
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setRowCount(len(rows))
    for r, values in enumerate(rows):
        for c, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            item.setForeground(_TEXT)
            table.setItem(r, c, item)
    fill_columns(table)
    table.resizeRowsToContents()
    shown = sum(table.rowHeight(r) for r in range(min(len(rows), _MAX_ROWS)))
    table.setFixedHeight(_HEADER_H + shown + 4 + (18 if len(rows) > _MAX_ROWS else 0))
    return table


class ProjectHistoryDialog(QDialog):
    def __init__(self, parent, project: str, history: ProjectHistory = None):
        super().__init__(parent)
        history = history or ProjectHistory()
        self.setWindowTitle("Project history")
        self.setModal(True)
        self.resize(980, 680)
        self.setStyleSheet(DIALOG_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)

        color = history.projects.get_project_colors().get(project, "#C7D3DB")
        title = QLabel(f"<span style='color:{color}'>&#9632;</span>&nbsp; {project}")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#000000;")
        root.addWidget(title)
        owner = history.projects.get_owner(project)
        if owner:
            by = QLabel(f"Owner: {owner}")
            by.setStyleSheet("font-size:12px; color:#000000;")
            root.addWidget(by)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(8)
        running, past = history.experiments(project)
        plans = history.plans(project)
        self.sections = {}
        self._section(lay, "Running now", ["Channel", "Owner", "Start", "Expected end", "Data filename"],
                      [[e["channel"], e["current_owner"], e["start_date"], e["expected_end_date"],
                        e["data_filename"]] for e in running])
        self._section(lay, "Planned", ["Requested by", "Status", "Urgency", "Test length [h]", "Channel"],
                      [[p["name"], p["status"].capitalize(), p["urgency"], p["test_length_h"],
                        p["channel"] or "Any cell"] for p in plans])
        self._section(lay, "Past", ["Channel", "Status", "Owner", "Start", "End", "Data filename"],
                      [[e["channel"], e["status"], e["current_owner"], e["start_date"], e["end_date"],
                        e["data_filename"]] for e in past])
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.setStyleSheet(_CLOSE_BTN)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def _section(self, lay, name: str, headers: list, rows: list) -> None:
        label = QLabel(f"{name}  ({len(rows)})")
        label.setStyleSheet("font-size:13px; font-weight:700; color:#000000; margin-top:6px;")
        lay.addWidget(label)
        if rows:
            table = _table(headers, rows)
            lay.addWidget(table)
        else:
            table = QLabel("None")
            table.setStyleSheet("font-size:12px; color:#6B7A86; margin-left:2px;")
            lay.addWidget(table)
        self.sections[name] = table
