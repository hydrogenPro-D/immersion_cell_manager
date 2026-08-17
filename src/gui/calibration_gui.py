"""IC Channel Calibration tab.

Summary view: one row per channel showing its latest calibration (date, IC
number, the six ΔV% values, decision status, note). Double-click a channel to
open its full history + border plot and Approve/Reject a measurement.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QGraphicsDropShadowEffect,
    QTabWidget, QStyledItemDelegate, QStyleOptionViewItem, QStyle,
)
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen

from src.data.calibration_manager import (
    CalibrationManager, MAX_CALIBRATION_AGE_DAYS, STATUS_FAIL,
)
from src.gui.styles.tab_styles import TAB_STYLE
from src.gui.widgets.calibration_detail_dialog import (
    CalibrationDetailDialog, STATUS_COLORS, apply_row_border_selection,
    install_row_toggle_deselect,
)
from src.gui.widgets.calibration_plot import CalibrationCurvesPlot

# Header for the colored calibration-age box (rename here if desired).
CALIBRATION_AGE_HEADER = "Calibration age"


def _lerp_hex(a: str, b: str, t: float) -> str:
    """Linearly interpolate between two #rrggbb colors (t in 0..1)."""
    a, b = a.lstrip("#"), b.lstrip("#")
    ch = [round(int(a[i:i + 2], 16) + (int(b[i:i + 2], 16) - int(a[i:i + 2], 16)) * t)
          for i in (0, 2, 4)]
    return "#{:02X}{:02X}{:02X}".format(*ch)


def freshness_color(age_days) -> str:
    """Fresh -> overdue as a light->dark ramp so it's readable when color-blind.

    Light green (fresh) -> orange -> dark red (>= max age). The brightness drops
    as it ages, so 'brighter = fresher' works even if the hues look alike;
    neutral gray means never tested.
    """
    if age_days is None:
        return "#CFD8DC"  # no date yet: not stale, just uncolored
    ratio = min(max(age_days / MAX_CALIBRATION_AGE_DAYS, 0.0), 1.0)
    if ratio < 0.5:  # light green -> orange over the first half
        return _lerp_hex("#B7E4A8", "#E8912B", ratio / 0.5)
    return _lerp_hex("#E8912B", "#C62828", (ratio - 0.5) / 0.5)  # orange -> red


# Item-data roles carrying the bar fill fraction (0..1) and its fill color.
FILL_ROLE = Qt.ItemDataRole.UserRole + 201
FILL_COLOR_ROLE = Qt.ItemDataRole.UserRole + 202


class _CalibrationBarDelegate(QStyledItemDelegate):
    """Draws the calibration-age cell as a progress bar: fill = days/90.

    The fill fraction and color come from the item's data roles; an empty gray
    track means never tested (fraction 0). Keeps the table's row-selection
    outline (top/bottom edges) so the middle column doesn't break the border.
    """

    TRACK_COLOR = "#E2E8EC"

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        # Draw the zebra background but not the selection/hover fill.
        opt.state &= ~(
            QStyle.StateFlag.State_Selected
            | QStyle.StateFlag.State_MouseOver
            | QStyle.StateFlag.State_HasFocus
        )
        super().paint(painter, opt, index)

        frac = float(index.data(FILL_ROLE) or 0.0)
        fill_hex = index.data(FILL_COLOR_ROLE) or self.TRACK_COLOR

        rect = option.rect
        pad_x, bar_h = 8, 16
        track = QRectF(
            rect.left() + pad_x,
            rect.top() + (rect.height() - bar_h) / 2,
            max(0, rect.width() - 2 * pad_x),
            bar_h,
        )
        r = bar_h / 2
        path = QPainterPath()
        path.addRoundedRect(track, r, r)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillPath(path, QColor(self.TRACK_COLOR))
        if frac > 0:
            painter.setClipPath(path)  # rounded left end, flat right end
            painter.fillRect(
                QRectF(track.left(), track.top(), track.width() * frac, track.height()),
                QColor(fill_hex),
            )
            painter.setClipping(False)
        painter.restore()

        # Keep the row outline continuous across this (middle) column: top/bottom
        # only, matching the selected (thick) / hovered (thin) teal border.
        hovered = getattr(self.parent(), "_hover_row", -1) == index.row()
        if selected or hovered:
            color, width = (QColor("#1F6B6B"), 2) if selected else (QColor("#3FA3A3"), 1)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setPen(QPen(color, width))
            painter.drawLine(rect.left(), rect.top(), rect.right(), rect.top())
            painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
            painter.restore()


class CalibrationTab(QWidget):
    """One-row-per-channel calibration summary; opens a detail dialog per channel."""

    def __init__(self, manager, on_decision=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        # on_decision(channel, passed), couples a verdict to the cell status.
        self.on_decision = on_decision
        self.init_ui()
        self.reload_data()

    # ----------------------------------------------------------------- UI
    def init_ui(self):
        self.setObjectName("TabRoot")
        self.setStyleSheet(TAB_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._build_header())

        self.table = QTableWidget()
        self.table.setObjectName("DataTable")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)  # multiline notes wrap + grow the row
        self.table.verticalHeader().setVisible(False)
        # Selected row = thin black outline (keeps the Status pill colors);
        # re-click the selected row to deselect it.
        apply_row_border_selection(self.table)
        install_row_toggle_deselect(self.table)
        self.table.doubleClicked.connect(self._on_row_activated)
        # Style the header/frame only (not ::item) so the status-pill cell
        # background colors set per row still show through.
        self.table.setStyleSheet(
            "QTableWidget { background:#FFFFFF; border:1px solid #E1E8ED;"
            " border-radius:8px; gridline-color:#EEF2F5; }"
            "QHeaderView::section { background:#E2EAEF; color:#4A5A66;"
            " padding:6px 8px; border:none; font-weight:600; }"
        )

        headers = ["Channel", "Date", CALIBRATION_AGE_HEADER, "IC number"] + \
            [f"ΔV% {r:g}Ω" for r in self.manager.resistances()] + ["Status", "Note"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
        # Give the Status column extra room so the pills aren't cramped.
        status_col = len(headers) - 2
        header.setSectionResizeMode(status_col, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(status_col, 140)
        # Fixed width for the calibration-age progress bar.
        self._age_col = 2
        header.setSectionResizeMode(self._age_col, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self._age_col, 120)
        self.table.setItemDelegateForColumn(
            self._age_col, _CalibrationBarDelegate(self.table)
        )

        # Two sub-tabs: the measurements table and the calibration-curves plot,
        # each getting the full width.
        self.curves_plot = CalibrationCurvesPlot()

        sub_tabs = QTabWidget()
        sub_tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #E1E8ED; top: -1px; }"
            "QTabBar::tab { padding: 8px 22px; margin-right: 2px; background: #F5F5F5;"
            " color: #1F1F1F; font-weight: 500; border-top-left-radius: 6px;"
            " border-top-right-radius: 6px; }"
            "QTabBar::tab:selected { background: #FFFFFF; color: #3FA3A3;"
            " border-bottom: 2px solid #3FA3A3; }"
            "QTabBar::tab:hover { background: #ECECEC; }"
        )
        sub_tabs.addTab(self.table, "Table")
        sub_tabs.addTab(self.curves_plot, "Plot")
        root.addWidget(sub_tabs, 1)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("PageHeader")
        header.setFixedHeight(70)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        title = QLabel("Channel Calibration")
        title.setObjectName("PageTitle")
        layout.addWidget(title, 1)

        self.count_badge = QLabel("0 channels")
        self.count_badge.setObjectName("PageBadge")
        self.count_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.count_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(63, 163, 163, 90))
        header.setGraphicsEffect(shadow)
        return header

    # --------------------------------------------------------------- Data
    def reload_data(self):
        records = self.manager.get_latest_per_channel()
        self.table.setRowCount(len(records))
        for r, rec in enumerate(records):
            col = 0
            for value in (rec["channel"], rec["measured_date"]):
                self.table.setItem(r, col, QTableWidgetItem(value))
                col += 1
            # Calibration-age progress bar: fill = days/90, colored fresh->overdue.
            # A failed calibration disables the bar (its age is moot, it needs
            # re-testing), shown as an empty track.
            age = CalibrationManager.age_days(rec["measured_date"])
            box = QTableWidgetItem("")
            if rec["status"] == STATUS_FAIL:
                box.setData(FILL_ROLE, 0.0)
                box.setData(FILL_COLOR_ROLE, freshness_color(None))
                box.setToolTip("Last calibration failed.")
            else:
                frac = 0.0 if age is None else min(age / MAX_CALIBRATION_AGE_DAYS, 1.0)
                box.setData(FILL_ROLE, frac)
                box.setData(FILL_COLOR_ROLE, freshness_color(age))
                if age is None:
                    box.setToolTip("Never calibrated.")
                elif age >= MAX_CALIBRATION_AGE_DAYS:
                    box.setToolTip(f"{age} days since last calibration, overdue "
                                   "(can't be set In use).")
                else:
                    box.setToolTip(f"{age} days since last calibration.")
            self.table.setItem(r, col, box)
            col += 1
            self.table.setItem(r, col, QTableWidgetItem(rec["ic_number"]))
            col += 1
            for d in rec["deltas"]:
                text = "-" if d is None else f"{d:.2f}"
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, col, item)
                col += 1
            status = rec["status"]
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            bg, fg = STATUS_COLORS.get(status, ("#E2EAEF", "#4A5A66"))
            status_item.setBackground(QColor(bg))
            status_item.setForeground(QColor(fg))
            self.table.setItem(r, col, status_item)
            col += 1
            self.table.setItem(r, col, QTableWidgetItem(rec["note"]))

        # Grow rows to fit multiline notes (word wrap is on).
        self.table.resizeRowsToContents()

        # Curves plot: one interpolated curve per channel with a complete
        # (all six ΔV%) latest measurement.
        series = [{"channel": rec["channel"], "status": rec["status"],
                   "deltas": rec["deltas"]}
                  for rec in records
                  if all(d is not None for d in rec["deltas"])]
        self.curves_plot.set_data(
            self.manager.resistances(), series, self.manager.bounds()
        )

        n = len(records)
        self.count_badge.setText(f"{n} channel{'s' if n != 1 else ''}")

    def _on_row_activated(self, index):
        row = index.row()
        channel_item = self.table.item(row, 0)
        if channel_item is None:
            return
        channel = channel_item.text().strip()
        if not channel:
            return
        dialog = CalibrationDetailDialog(
            channel, self.manager, self, on_decision=self.on_decision
        )
        dialog.exec()
        # Measurements or decisions may have changed while the dialog was open.
        self.reload_data()
