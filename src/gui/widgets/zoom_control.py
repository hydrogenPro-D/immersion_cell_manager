"""A small, reusable zoom control (− / percentage / +).

Shared by the Cells Mapping and Station Summary toolbars so there is a single
zoom widget. It is agnostic about what it zooms: ``on_zoom(direction)`` performs
the zoom (``direction`` is +1 or -1) and returns the applied zoom factor
(``1.0`` == 100%), which the control shows in its label.
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt


class ZoomControl(QWidget):
    """Reusable zoom-out / percentage / zoom-in button group."""

    _BTN_STYLE = (
        "QPushButton { background:#E2EAEF; color:#2C3E50; border:none;"
        " border-radius:6px; font-size:16px; font-weight:700; }"
        " QPushButton:hover { background:#D0DCE5; }"
        " QPushButton:pressed { background:#BCCDD8; }"
    )

    def __init__(self, on_zoom, parent=None):
        super().__init__(parent)
        self._on_zoom = on_zoom

        row = QHBoxLayout(self)
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel("100%")
        self._label.setObjectName("PageBadge")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Wide enough for a 3-digit percentage (e.g. "200%") without cropping.
        self._label.setFixedWidth(60)

        row.addWidget(self._make_button("－", "Zoom out (smaller rows & text)", -1))
        row.addWidget(self._label)
        row.addWidget(self._make_button("＋", "Zoom in (larger rows & text)", 1))

    def _make_button(self, text: str, tooltip: str, direction: int) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(self._BTN_STYLE)
        btn.clicked.connect(lambda: self._change(direction))
        return btn

    def _change(self, direction: int) -> None:
        applied = self._on_zoom(direction)
        self._label.setText(f"{round(applied * 100)}%")
