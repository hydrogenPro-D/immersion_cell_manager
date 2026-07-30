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

# Set truthy on an item (via setData) to draw a red "!" warning badge on its pill.
WARN_ROLE = Qt.ItemDataRole.UserRole + 137


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
        enable_hover: bool = True,
    ):
        super().__init__(parent)
        self._resolve = color_resolver
        self._enable_hover = enable_hover
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
        if index.data(WARN_ROLE):
            w += 28  # room for the trailing "!" badge
        h = fm.height() + self._vp * 2 + self._row_pad_y * 2
        return QSize(w, h)

    # ------------------------------------------------------------------
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        bg, fg = self._resolve(text)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Background behind the pill. A row tint set on the item (e.g. the
        # pending-calibration highlight) wins over hover so hovering a tinted
        # cell doesn't change its color; selection still takes precedence.
        brush = index.data(Qt.ItemDataRole.BackgroundRole)
        if option.state & option.state.State_Selected:
            gradient = QLinearGradient(0, option.rect.top(), 0, option.rect.bottom())
            gradient.setColorAt(0, QColor("#BFE6E6"))
            gradient.setColorAt(1, QColor("#9ED6D6"))
            painter.fillRect(option.rect, gradient)
        elif brush is not None:
            painter.fillRect(option.rect, brush)
        elif self._enable_hover and option.state & option.state.State_MouseOver:
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

        # Red "!" badge for flagged cells (e.g. a stale calibration), drawn just
        # to the right of the pill.
        if index.data(WARN_ROLE):
            d = min(pill_h, 20)
            bx = pill_rect.right() + 8
            by = option.rect.top() + (option.rect.height() - d) // 2
            badge = QRect(bx, by, d, d)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#D32F2F")))
            painter.drawEllipse(badge)
            painter.setPen(QColor("#FFFFFF"))
            bf: QFont = painter.font()
            bf.setWeight(QFont.Weight.Bold)
            painter.setFont(bf)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "!")

        painter.restore()

