"""Read-only list table shared by the IC Logbook and Event Log tabs.

Teal header like the Cells mapping table, and whole-row borders instead of fills
for hover / selection.
"""

import unicodedata

from PyQt6.QtWidgets import (
    QTableWidget, QAbstractItemView, QHeaderView, QStyledItemDelegate,
    QStyleOptionViewItem, QStyle, QApplication,
)
from PyQt6.QtCore import Qt, QEvent, QRect, QSize
from PyQt6.QtGui import QColor, QIcon, QPen

# An icon drawn right after a cell's text (Qt's own icon always goes first).
TRAILING_ICON_ROLE = Qt.ItemDataRole.UserRole + 52
_TRAILING_SIZE, _TRAILING_GAP = 14, 6

HOVER_TABLE_STYLE = (
    "QTableWidget { background:#FFFFFF; border:1px solid #E1E8ED;"
    " border-radius:8px; gridline-color:#EEF2F5;"
    " alternate-background-color:#F7FAFC; }"  # same row striping as Cells mapping
    # Teal header, same look as the Cells mapping table.
    "QHeaderView { background:transparent; border:none; }"
    "QHeaderView::section { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    " stop:0 #55BDBD, stop:1 #3FA3A3); color:#FFFFFF; padding:6px 14px;"
    " border:none; border-right:1px solid rgba(255,255,255,0.18);"
    " font-weight:600; font-size:12px; letter-spacing:0.4px; }"
    "QHeaderView::section:hover { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    " stop:0 #62CACA, stop:1 #46B0B0); }"
    "QHeaderView::section:first { border-top-left-radius:8px; }"
    "QHeaderView::section:last { border-right:none; border-top-right-radius:8px; }"
)


def fit_columns(table: QTableWidget) -> None:
    """Size columns to their contents and let the last one fill the width.

    The last column is skipped on purpose: resizing it to contents after stretch
    is on shrinks it until the next resize event (the half-width table bug).
    """
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(True)
    for c in range(table.columnCount() - 1):
        table.resizeColumnToContents(c)


def fill_columns(table: "HoverBorderTable", max_width: int = 400) -> None:
    """Size columns to their contents (at most ``max_width``: long text wraps);
    spare width is shared out in proportion to those widths. Too little width:
    a horizontal scrollbar instead."""
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(False)
    table.resizeColumnsToContents()
    table._natural_widths = [min(table.columnWidth(c), max_width)
                             for c in range(table.columnCount())]
    table._spread_columns()


class RowHoverBorderDelegate(QStyledItemDelegate):
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
        icon = index.data(TRAILING_ICON_ROLE)
        if isinstance(icon, QIcon):
            self._paint_trailing(painter, option, index, icon)

        if selected:
            self._border(painter, option, index, self.SELECTED, 2)
        elif getattr(self.parent(), "_hover_row", -1) == index.row():
            self._border(painter, option, index, self.HOVER, 1)

    def _paint_trailing(self, painter, option, index, icon) -> None:
        o = QStyleOptionViewItem(option)
        self.initStyleOption(o, index)
        style = o.widget.style() if o.widget else QApplication.style()
        text = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, o, o.widget)
        x = text.left() + o.fontMetrics.horizontalAdvance(o.text) + _TRAILING_GAP
        y = option.rect.center().y() - _TRAILING_SIZE // 2 + 1
        icon.paint(painter, QRect(x, y, _TRAILING_SIZE, _TRAILING_SIZE))

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if isinstance(index.data(TRAILING_ICON_ROLE), QIcon):
            size = QSize(size.width() + _TRAILING_GAP + _TRAILING_SIZE, size.height())
        return size

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


class HoverBorderTable(QTableWidget):
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
        self.setItemDelegate(RowHoverBorderDelegate(self))
        if selectable:
            self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        else:
            self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        # Set by fill_columns: content widths that _spread_columns scales up.
        self._natural_widths = None
        self._scale = 1.0
        self._spreading = False
        self.horizontalHeader().sectionResized.connect(self._on_section_resized)

    # ---------------------------------------------- Proportional column fill
    def _spread_columns(self) -> None:
        natural = self._natural_widths
        if not natural or len(natural) != self.columnCount():
            return
        avail = self.viewport().width()
        self._scale = max(1.0, avail / sum(natural)) if sum(natural) else 1.0
        widths = [int(w * self._scale) for w in natural]
        if self._scale > 1.0:
            widths[-1] += avail - sum(widths)  # rounding leftovers; no scrollbar
        self._spreading = True
        for c, w in enumerate(widths):
            self.setColumnWidth(c, w)
        self._spreading = False

    def _on_section_resized(self, column: int, _old: int, new: int) -> None:
        # A border dragged by the user becomes that column's base width.
        if self._natural_widths and not self._spreading and column < len(self._natural_widths):
            self._natural_widths[column] = max(20, round(new / self._scale))

    def viewportEvent(self, event):
        result = super().viewportEvent(event)
        if event.type() == QEvent.Type.Resize:
            self._spread_columns()  # also when the vertical scrollbar comes or goes
        return result

    # ------------------------------------------------------- Header sorting
    _ORIGINAL_ROW = Qt.ItemDataRole.UserRole + 50  # row's position before sorting
    SORT_ROLE = Qt.ItemDataRole.UserRole + 51  # optional number to sort by instead of the text

    def enable_header_sort(self) -> None:
        """Click a header to sort, like the Cells mapping table: ascending, then
        descending, then back to the original order. Call after the headers are
        set; call :meth:`apply_sort` after each refill."""
        self._sort = (None, False)  # (column, descending)
        self._base_labels = [self.horizontalHeaderItem(c).text()
                             for c in range(self.columnCount())]
        header = self.horizontalHeader()
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._on_header_clicked)

    def _on_header_clicked(self, column: int) -> None:
        col, desc = self._sort
        if col != column:
            self._sort = (column, False)
        elif not desc:
            self._sort = (column, True)
        else:
            self._sort = (None, False)
        self.apply_sort()
        if self._natural_widths:
            # Room for the ▲ / ▼, then share the width out again.
            self._natural_widths[column] = max(self.sizeHintForColumn(column),
                                               self.horizontalHeader().sectionSizeHint(column))
            self._spread_columns()
        elif column < self.columnCount() - 1:  # the last one stretches anyway
            self.resizeColumnToContents(column)  # room for the ▲ / ▼

    @staticmethod
    def _sort_key(text: str):
        # Numbers sort as numbers and before text; text ignores case and accents
        # (so "Ádám" sorts with the A's).
        try:
            return (0, float(text.replace(",", "")), "")
        except ValueError:
            plain = "".join(ch for ch in unicodedata.normalize("NFKD", text.lower())
                            if not unicodedata.combining(ch))
            return (1, 0.0, plain)

    @classmethod
    def _item_key(cls, item):
        value = item.data(cls.SORT_ROLE) if item is not None else None
        if value is not None:
            return (0, float(value), "")
        return cls._sort_key(item.text() if item is not None else "")

    def apply_sort(self) -> None:
        """(Re)apply the current sort; with none, restore the original order."""
        if not hasattr(self, "_sort"):
            return
        rows = [[self.takeItem(r, c) for c in range(self.columnCount())]
                for r in range(self.rowCount())]
        for r, row in enumerate(rows):  # freshly filled rows: remember their order
            if row[0] is not None and row[0].data(self._ORIGINAL_ROW) is None:
                row[0].setData(self._ORIGINAL_ROW, r)
        col, desc = self._sort
        if col is None:
            rows.sort(key=lambda row: row[0].data(self._ORIGINAL_ROW) if row[0] else 0)
        else:
            rows.sort(key=lambda row: self._item_key(row[col]), reverse=desc)
        for r, row in enumerate(rows):
            for c, item in enumerate(row):
                if item is not None:
                    self.setItem(r, c, item)
        for c, label in enumerate(self._base_labels):
            arrow = "" if c != col else (" ▼" if desc else " ▲")
            self.horizontalHeaderItem(c).setText(label + arrow)
        self.resizeRowsToContents()

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
