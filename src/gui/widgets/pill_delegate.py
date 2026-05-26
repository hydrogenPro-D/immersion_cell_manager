"""Item delegate that paints a value as a rounded colored "pill" badge.

The delegate is independent of where it's used — both ``QComboBox`` popups and
``QTableWidget`` cells can install it. It looks up the colour for the cell's
text via a ``color_resolver`` callable that returns ``(background, foreground)``
hex strings.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QFont, QLinearGradient
from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem


ColorResolver = Callable[[str], tuple[str, str]]


class PillDelegate(QStyledItemDelegate):
    """Render the item's text as a rounded pill in the resolved colours."""

    def __init__(
        self,
        color_resolver: ColorResolver,
        parent=None,
        h_padding: int = 12,
        v_padding: int = 4,
        radius: int = 11,
        row_padding_x: int = 8,
        row_padding_y: int = 4,
    ):
        super().__init__(parent)
        self._resolve = color_resolver
        self._hp = h_padding
        self._vp = v_padding
        self._radius = radius
        self._row_pad_x = row_padding_x
        self._row_pad_y = row_padding_y

    # ------------------------------------------------------------------
    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        fm = option.fontMetrics
        w = fm.horizontalAdvance(str(text)) + self._hp * 2 + self._row_pad_x * 2
        h = fm.height() + self._vp * 2 + self._row_pad_y * 2
        return QSize(w, h)

    # ------------------------------------------------------------------
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        bg, fg = self._resolve(text)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Selection or hover background for the whole row
        if option.state & option.state.State_Selected:
            # Use the same gradient as the table stylesheet
            gradient = QLinearGradient(0, option.rect.top(), 0, option.rect.bottom())
            gradient.setColorAt(0, QColor("#BFE6E6"))
            gradient.setColorAt(1, QColor("#9ED6D6"))
            painter.fillRect(option.rect, gradient)
        elif option.state & option.state.State_MouseOver:
            painter.fillRect(option.rect, QColor("#F4F8FA"))

        # Pill geometry — vertically centered, left-aligned with row padding
        fm = option.fontMetrics
        text_w = fm.horizontalAdvance(text)
        pill_w = text_w + self._hp * 2
        pill_h = fm.height() + self._vp * 2

        pill_rect = QRect(
            option.rect.left() + self._row_pad_x,
            option.rect.top() + (option.rect.height() - pill_h) // 2,
            pill_w,
            pill_h,
        )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(bg)))
        painter.drawRoundedRect(pill_rect, self._radius, self._radius)

        painter.setPen(QColor(fg))
        font: QFont = painter.font()
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, text)

        painter.restore()

