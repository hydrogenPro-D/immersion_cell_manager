"""Read-only dialog that lists all information about a station-summary bar.

Opened when the user double-clicks an episode bar in the Station Summary Gantt
chart. It mirrors the look of :class:`EditRowDialog` (rounded card, gradient
header, scrollable body) but every field is shown as plain read-only text — the
dialog only presents information and cannot edit anything.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QWidget,
    QGraphicsDropShadowEffect,
    QDialogButtonBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from src.gui.styles.dialog_styles import DIALOG_STYLE


class EpisodeInfoDialog(QDialog):
    """A modal, read-only details view for a single timeline episode."""

    # Raw record keys that should not be shown as-is (internal / re-labeled).
    _HIDDEN_KEYS = {"color"}
    # Friendlier labels for a few stored keys.
    _KEY_LABELS = {"end_date": "End date"}
    # Preferred display order; any remaining keys are appended afterwards.
    _PREFERRED_ORDER = [
        "Channel",
        "Project ID",
        "Current owner",
        "Assembled by",
        "Status",
        "Start date",
        "end_date",
        "Duration",
        "Cathode",
        "Anode",
        "Data filename",
        "Added water by timing",
        "Comments",
    ]

    def __init__(self, episode: dict, parent=None):
        super().__init__(parent)
        self.episode = episode or {}
        self.init_ui()

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        self.setWindowTitle("Channel details")
        self.setModal(True)
        self.resize(560, 560)

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

        title = QLabel(self._dialog_title())
        title.setObjectName("DialogTitle")
        subtitle = QLabel("Read-only details for this timeline entry.")
        subtitle.setObjectName("DialogSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        return header

    def _dialog_title(self) -> str:
        data = self.episode.get("data", {})
        channel = (data.get("Channel") or "").strip()
        if channel:
            return f"Channel {channel}"
        return "Channel details"

    def _build_body(self) -> QFrame:
        body = QFrame()
        body.setObjectName("DialogBody")

        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(28, 26, 28, 22)
        body_layout.setSpacing(20)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        form = QVBoxLayout(content)
        form.setContentsMargins(0, 0, 8, 0)
        form.setSpacing(16)

        for label, value in self._info_items():
            form.addLayout(self._build_row(label, value))

        form.addStretch(1)
        scroll.setWidget(content)
        body_layout.addWidget(scroll, 1)

        # Bottom action row: just a Close button.
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn = button_box.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            close_btn.setDefault(True)
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.accept)
        body_layout.addWidget(button_box)

        return body

    def _build_row(self, label_text: str, value_text: str) -> QVBoxLayout:
        row = QVBoxLayout()
        row.setSpacing(6)

        label = QLabel(label_text.upper())
        label.setObjectName("FieldLabel")

        value = QLabel(value_text if value_text else "—")
        value.setObjectName("InfoValue")
        value.setWordWrap(True)
        value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        value.setStyleSheet(
            "QLabel#InfoValue {"
            " background-color: #EEF3F6; color: #1F2A33;"
            " border: 1px dashed #C7D3DB; border-radius: 8px;"
            " padding: 9px 12px; font-size: 13px; }"
        )

        row.addWidget(label)
        row.addWidget(value)
        return row

    # ----------------------------------------------------------------- Data
    def _info_items(self) -> list[tuple[str, str]]:
        """Return ``[(label, value), ...]`` describing the episode."""
        data = dict(self.episode.get("data", {}))

        ordered_keys = []
        for key in self._PREFERRED_ORDER:
            if key in data:
                ordered_keys.append(key)
        # Append any extra keys not covered by the preferred order.
        for key in data:
            if key not in ordered_keys and key not in self._HIDDEN_KEYS:
                ordered_keys.append(key)

        items = []
        for key in ordered_keys:
            if key in self._HIDDEN_KEYS:
                continue
            label = self._KEY_LABELS.get(key, key)
            value = str(data.get(key, "") or "").strip()
            items.append((label, value))
        return items

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


