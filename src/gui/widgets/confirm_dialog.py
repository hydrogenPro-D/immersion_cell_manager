"""A reusable, prettified confirmation dialog ("Are you sure?" box).

Visually mirrors :class:`EditRowDialog`, a frameless card with a gradient
teal (or red, when destructive) header banner and a white body.

Use :meth:`ConfirmDialog.ask` for a one-liner:

    if ConfirmDialog.ask(self, "Remove Immersion Cell",
                         "Delete channel <b>2-3</b>?",
                         "This action cannot be undone.",
                         confirm_text="Yes, delete",
                         destructive=True):
        ...
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from src.gui.styles.dialog_styles import DIALOG_STYLE


_EXTRA_STYLE = """
    /* Card body, same look as EditRowDialog's #DialogBody. */
    QFrame#ConfirmBody {
        background-color: #FFFFFF;
        border-bottom-left-radius: 12px;
        border-bottom-right-radius: 12px;
        border: 1px solid #D8E2E8;
        border-top: none;
    }

    /* Gradient header banner, variant decides the palette. */
    QFrame#ConfirmHeader {
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
        border: none;
    }
    QFrame#ConfirmHeader[variant="primary"] {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #55BDBD, stop:1 #3FA3A3);
    }
    QFrame#ConfirmHeader[variant="destructive"] {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #E76F7E, stop:1 #B23A48);
    }

    QLabel#ConfirmHeaderIcon {
        color: #FFFFFF;
        background: transparent;
        font-size: 26px;
    }
    QLabel#ConfirmHeaderTitle {
        color: #FFFFFF;
        background: transparent;
        font-size: 18px;
        font-weight: 600;
        letter-spacing: 0.4px;
    }
    QLabel#ConfirmHeaderSubtitle {
        color: rgba(255, 255, 255, 0.85);
        background: transparent;
        font-size: 12px;
    }

    QLabel#ConfirmMessage {
        color: #1F2A33;
        font-size: 13px;
        background: transparent;
    }
    QLabel#ConfirmInfo {
        color: #6B7A85;
        font-size: 12px;
        background: transparent;
    }

    /* Buttons share the shape/typography used in tab_styles primary/danger. */
    QPushButton#ConfirmPrimary,
    QPushButton#ConfirmDanger,
    QPushButton#ConfirmGhost {
        min-width: 120px;
        padding: 10px 20px;
        border-radius: 10px;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.4px;
    }

    QPushButton#ConfirmPrimary {
        color: #FFFFFF;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #55BDBD, stop:1 #3FA3A3);
        border: 1px solid #3FA3A3;
    }
    QPushButton#ConfirmPrimary:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #62CACA, stop:1 #46B0B0);
    }
    QPushButton#ConfirmPrimary:pressed {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #3FA3A3, stop:1 #2F8B8B);
    }

    QPushButton#ConfirmDanger {
        color: #FFFFFF;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #E76F7E, stop:1 #B23A48);
        border: 1px solid #B23A48;
    }
    QPushButton#ConfirmDanger:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #EF8492, stop:1 #C04654);
    }
    QPushButton#ConfirmDanger:pressed {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #B23A48, stop:1 #8E2A37);
    }

    QPushButton#ConfirmGhost {
        color: #4A5A66;
        background-color: #FFFFFF;
        border: 1px solid #D8E2E8;
    }
    QPushButton#ConfirmGhost:hover {
        background-color: #F0F4F6;
        border-color: #BBD0D8;
        color: #1F2A33;
    }
    QPushButton#ConfirmGhost:pressed {
        background-color: #E2EAEF;
    }
"""


class ConfirmDialog(QDialog):
    """Confirmation dialog styled to match :class:`EditRowDialog`."""

    def __init__(
        self,
        parent=None,
        title: str = "Are you sure?",
        message: str = "Do you want to continue?",
        informative: str = "",
        confirm_text: str = "Yes",
        cancel_text: str = "Cancel",
        destructive: bool = False,
        icon: str | None = None,
        subtitle: str | None = None,
        single: bool = False,
    ):
        super().__init__(parent)
        self._title = title
        self._message = message
        self._informative = informative
        self._confirm_text = confirm_text
        self._cancel_text = cancel_text
        self._destructive = destructive
        self._single = single  # single-button acknowledgement (no Cancel)
        self._icon = icon if icon is not None else ("⚠️" if destructive else "❓")
        self._subtitle = subtitle if subtitle is not None else (
            "Please confirm, this cannot be undone." if destructive
            else "Please confirm to continue."
        )
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.setWindowTitle(self._title)
        self.setModal(True)
        self.setMinimumWidth(460)

        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(DIALOG_STYLE + _EXTRA_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("ConfirmCard")
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
        header.setObjectName("ConfirmHeader")
        header.setProperty(
            "variant", "destructive" if self._destructive else "primary"
        )
        header.setFixedHeight(80)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(14)

        icon = QLabel(self._icon)
        icon.setObjectName("ConfirmHeaderIcon")
        icon.setFixedWidth(34)
        icon.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title_lbl = QLabel(self._title)
        title_lbl.setObjectName("ConfirmHeaderTitle")

        subtitle_lbl = QLabel(self._subtitle)
        subtitle_lbl.setObjectName("ConfirmHeaderSubtitle")

        text_col.addWidget(title_lbl)
        text_col.addWidget(subtitle_lbl)
        layout.addLayout(text_col, 1)

        return header

    def _build_body(self) -> QFrame:
        body = QFrame()
        body.setObjectName("ConfirmBody")

        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(10)

        message_lbl = QLabel(self._message)
        message_lbl.setObjectName("ConfirmMessage")
        message_lbl.setWordWrap(True)
        message_lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(message_lbl)

        if self._informative:
            info_lbl = QLabel(self._informative)
            info_lbl.setObjectName("ConfirmInfo")
            info_lbl.setWordWrap(True)
            layout.addWidget(info_lbl)

        layout.addSpacing(12)
        layout.addLayout(self._build_button_row())
        return body

    def _build_button_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)

        if not self._single:
            cancel_btn = QPushButton(self._cancel_text)
            cancel_btn.setObjectName("ConfirmGhost")
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel_btn.clicked.connect(self.reject)
            cancel_btn.setAutoDefault(False)
            cancel_btn.setDefault(True)  # safer default = Cancel
            row.addWidget(cancel_btn)

        confirm_btn = QPushButton(self._confirm_text)
        # A single-button acknowledgement keeps the friendly teal button even
        # under a warning (red) header.
        confirm_btn.setObjectName(
            "ConfirmDanger" if self._destructive and not self._single
            else "ConfirmPrimary"
        )
        confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_btn.clicked.connect(self.accept)
        confirm_btn.setAutoDefault(False)
        confirm_btn.setDefault(self._single)
        row.addWidget(confirm_btn)
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
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        super().mouseMoveEvent(event)

    # ---------------------------------------------------- Convenience API
    @classmethod
    def ask(
        cls,
        parent,
        title: str,
        message: str,
        informative: str = "",
        confirm_text: str = "Yes",
        cancel_text: str = "Cancel",
        destructive: bool = False,
        icon: str | None = None,
        subtitle: str | None = None,
    ) -> bool:
        """Show the dialog modally and return ``True`` if the user confirmed."""
        dialog = cls(
            parent=parent,
            title=title,
            message=message,
            informative=informative,
            confirm_text=confirm_text,
            cancel_text=cancel_text,
            destructive=destructive,
            icon=icon,
            subtitle=subtitle,
        )
        return dialog.exec() == QDialog.DialogCode.Accepted

    @classmethod
    def alert(
        cls,
        parent,
        title: str,
        message: str,
        informative: str = "",
        button_text: str = "OK",
        subtitle: str | None = None,
        icon: str | None = None,
        destructive: bool = True,
    ) -> None:
        """Show a fancy single-button warning/notice (no Cancel)."""
        cls(
            parent=parent,
            title=title,
            message=message,
            informative=informative,
            confirm_text=button_text,
            destructive=destructive,
            icon=icon,
            subtitle=subtitle,
            single=True,
        ).exec()

