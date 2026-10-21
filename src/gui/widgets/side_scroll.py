"""A one-row strip that scrolls sideways when the window is too narrow.

Wraps a toolbar so its full width no longer sets the window's minimum width:
with room it looks unchanged; without, a thin horizontal scrollbar appears
under it.
"""

from PyQt6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QWidget
from PyQt6.QtCore import Qt, QSize, QEvent

_BAR_HEIGHT = 8
_STYLE = (
    "QScrollArea { background: transparent; border: none; }"
    f"QScrollBar:horizontal {{ height:{_BAR_HEIGHT}px; background:transparent; border:none; }}"
    "QScrollBar::handle:horizontal { background:#C7D3DB; border-radius:4px; min-width:40px; }"
    "QScrollBar::handle:horizontal:hover { background:#A9B8C2; }"
    "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0px; }"
    "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:none; }"
)


class SideScroll(QScrollArea):
    def __init__(self, content: QWidget, parent=None):
        super().__init__(parent)
        self.setWidget(content)
        self.setWidgetResizable(True)  # content fills the width when there's room
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # See-through, so the toolbar's own background shows.
        self.setStyleSheet(_STYLE)
        self.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Styles and refilled dropdowns change the row's size after this point.
        content.installEventFilter(self)
        self._fit_height()

    def _height(self) -> int:
        h = self.widget().sizeHint().height()
        if self.widget().minimumSizeHint().width() > self.viewport().width():
            h += _BAR_HEIGHT  # room for the bar under the row
        return h

    def _fit_height(self) -> None:
        h = self._height()
        if h != self.height():
            self.setFixedHeight(h)

    def eventFilter(self, obj, event):
        if obj is self.widget() and event.type() in (QEvent.Type.LayoutRequest,
                                                      QEvent.Type.Polish):
            self._fit_height()
        return super().eventFilter(obj, event)

    def minimumSizeHint(self) -> QSize:
        return QSize(80, self._height())

    def sizeHint(self) -> QSize:
        return QSize(self.widget().sizeHint().width(), self._height())

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()
