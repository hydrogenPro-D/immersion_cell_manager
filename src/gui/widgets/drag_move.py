"""Drag a frameless window by its background."""

from PyQt6.QtCore import Qt


class DragMoveMixin:
    """Put before QDialog in the bases. A left press on the window's background
    hands the move to the OS, so no leftover drag offset can jump the window."""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)
