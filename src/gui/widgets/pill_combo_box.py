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
        # Everything is drawn with this single painter; creating a second
        # QPainter on the same widget while this one is active is an error and
        # silently drops whatever the second painter tries to draw.
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)

        # Draw frame (the stylesheet hides the native arrow) without the text.
        option.currentText = ""
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Current value as a colored pill.
        text = self.currentText()
        if text:
            bg, fg = self._resolve(text)
            text_rect: QRect = self.style().subControlRect(
                QStyle.ComplexControl.CC_ComboBox,
                option,
                QStyle.SubControl.SC_ComboBoxEditField,
                self,
            )
            fm = self.fontMetrics()
            h_pad, v_pad = 12, 3
            pill_w = fm.horizontalAdvance(text) + h_pad * 2
            pill_h = fm.height() + v_pad * 2
            pill_rect = QRect(
                text_rect.left() + 2,
                text_rect.top() + (text_rect.height() - pill_h) // 2,
                pill_w,
                pill_h,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(bg)))
            painter.drawRoundedRect(pill_rect, pill_h // 2, pill_h // 2)
            painter.setPen(QColor(fg))
            font: QFont = painter.font()
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, text)

        # Always-visible dropdown arrow on the right (the stylesheet hides the
        # native one), so it's obvious this is a dropdown.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor("#4A5A66"))
        arrow_font: QFont = painter.font()
        arrow_font.setWeight(QFont.Weight.Normal)
        painter.setFont(arrow_font)
        arrow_rect = QRect(self.width() - 24, 0, 16, self.height())
        painter.drawText(arrow_rect, Qt.AlignmentFlag.AlignCenter, "▾")

