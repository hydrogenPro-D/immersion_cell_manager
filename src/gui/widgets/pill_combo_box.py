"""A QComboBox that renders both its current value and dropdown items as
rounded "pill" badges using colours from a resolver callable."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter
from PyQt6.QtWidgets import QComboBox, QStyle, QStyleOptionComboBox, QStylePainter

from src.gui.widgets.pill_delegate import PillDelegate


ColorResolver = Callable[[str], tuple[str, str]]


class PillComboBox(QComboBox):
    """Combo box whose items render as colored pills."""

    def __init__(self, color_resolver: ColorResolver, parent=None):
        super().__init__(parent)
        self._resolve = color_resolver
        self.setItemDelegate(PillDelegate(color_resolver, self))

    def paintEvent(self, event):  # noqa: N802
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)

        # Draw frame + dropdown arrow without the default text
        option.currentText = ""
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)

        text = self.currentText()
        if not text:
            return

        bg, fg = self._resolve(text)
        text_rect: QRect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        )

        fm = self.fontMetrics()
        h_pad = 12
        v_pad = 3
        pill_w = fm.horizontalAdvance(text) + h_pad * 2
        pill_h = fm.height() + v_pad * 2
        pill_rect = QRect(
            text_rect.left() + 2,
            text_rect.top() + (text_rect.height() - pill_h) // 2,
            pill_w,
            pill_h,
        )

        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(QBrush(QColor(bg)))
        qp.drawRoundedRect(pill_rect, pill_h // 2, pill_h // 2)
        qp.setPen(QColor(fg))
        font: QFont = qp.font()
        font.setWeight(QFont.Weight.DemiBold)
        qp.setFont(font)
        qp.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, text)
        qp.end()

