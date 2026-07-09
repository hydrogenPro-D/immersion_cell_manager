"""Styled "changes saved" summary shown after modifying a station-summary episode.

Mirrors the look of :class:`EpisodeInfoDialog` (rounded card, gradient header,
name-left / value-right rows). Each row is one changed field shown as
``old → new``.
"""

from html import escape

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QWidget,
    QGraphicsDropShadowEffect,
    QPushButton,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from src.gui.styles.dialog_styles import DIALOG_STYLE


class ChangesDialog(QDialog):
    """Read-only summary of what changed on an episode (field: old → new)."""

    _STYLE = """
        QLabel#ChangeName {
            color: #6B7A85; font-size: 12px; font-weight: 600;
            letter-spacing: 0.2px; background: transparent;
        }
        QLabel#ChangeValue {
            color: #1F2A33; font-size: 14px; background: transparent;
        }
        QFrame#ChangeRow { border: none; border-bottom: 1px solid #EAF0F3; }
    """

    def __init__(self, channel, changes, parent=None):
        super().__init__(parent)
        self._channel = (channel or "").strip()
        self._changes = changes or []
        self.init_ui()

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        self.setWindowTitle("Changes saved")
        self.setModal(True)
        self.resize(600, 460)
        self.setMinimumSize(460, 280)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(DIALOG_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("DialogCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.addWidget(self._build_header())
        card_layout.addWidget(self._build_body(), 1)
        outer.addWidget(card)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(20, 50, 70, 90))
        card.setGraphicsEffect(shadow)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("DialogHeader")
        header.setFixedHeight(80)
        layout = QVBoxLayout(header)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(2)

        title = QLabel("Changes saved")
        title.setObjectName("DialogTitle")
        subtitle = QLabel(
            f"Channel {self._channel}" if self._channel else "Experiment updated"
        )
        subtitle.setObjectName("DialogSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return header

    def _build_body(self) -> QFrame:
        body = QFrame()
        body.setObjectName("DialogBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(28, 24, 28, 20)
        body_layout.setSpacing(16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        content = QWidget()
        content.setStyleSheet(self._STYLE)
        form = QVBoxLayout(content)
        form.setContentsMargins(0, 0, 8, 0)
        form.setSpacing(0)

        if self._changes:
            for label, old, new in self._changes:
                form.addWidget(self._build_row(label, old, new))
        else:
            note = QLabel("No fields were changed.")
            note.setObjectName("ChangeValue")
            form.addWidget(note)

        form.addStretch(1)
        scroll.setWidget(content)
        body_layout.addWidget(scroll, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.clicked.connect(self.accept)
        button_row.addWidget(ok_btn)
        body_layout.addLayout(button_row)
        return body

    def _build_row(self, label_text: str, old: str, new: str) -> QFrame:
        row = QFrame()
        row.setObjectName("ChangeRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 10, 2, 10)
        layout.setSpacing(16)

        name = QLabel(label_text)
        name.setObjectName("ChangeName")

        old_disp = escape(old) if old else "<i>(empty)</i>"
        new_disp = escape(new) if new else "<i>(empty)</i>"
        value = QLabel(
            f"<span style='color:#9AA7B0'>{old_disp}</span>"
            f" → "
            f"<span style='color:#1F2A33; font-weight:600'>{new_disp}</span>"
        )
        value.setObjectName("ChangeValue")
        value.setTextFormat(Qt.TextFormat.RichText)
        # No wrap: a long "old → new" extends and the scroll area shows a
        # horizontal scrollbar, instead of wrapping onto a clipped second line.
        value.setWordWrap(False)
        value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        layout.addWidget(
            name, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(
            value, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        return row

    # ---------------------------------------------------- Window dragging
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(
            self, "_drag_pos"
        ):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        super().mouseMoveEvent(event)
