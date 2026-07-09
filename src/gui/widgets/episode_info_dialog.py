"""Read-only dialog that lists all information about a station-summary bar.

Opened when the user double-clicks an episode bar in the Station Summary Gantt
chart. It mirrors the look of :class:`EditRowDialog` (rounded card, gradient
header, scrollable body) but every field is shown as plain read-only text — the
dialog only presents information and cannot edit anything.
"""

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
    QMessageBox,
    QSizeGrip,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from src.gui.styles.dialog_styles import DIALOG_STYLE


class EpisodeInfoDialog(QDialog):
    """A modal, read-only details view for a single timeline episode."""

    # Internal keys (plus ones merged/omitted below) never shown as their own row.
    _HIDDEN_KEYS = {
        "color", "id", "original_data_filename", "start_hour", "end_date",
    }
    # Stored (lower-case DB) keys in display order, with their friendly labels.
    # "start_date" also folds in start_hour (see _format_start); end_date omitted.
    _FIELDS = [
        ("channel", "Channel"),
        ("project_id", "Project ID"),
        ("status", "Status"),
        ("current_owner", "Current owner"),
        ("assembled_by", "Assembled by"),
        ("start_date", "Start date"),
        ("expected_end_date", "Expected end date"),
        ("cathode", "Cathode"),
        ("anode", "Anode"),
        ("separator", "Separator"),
        ("added_water_b", "Added water by timing"),
        ("data_filename", "Data filename"),
        ("comments", "Comments"),
    ]

    # Two-column summary rows: muted name on the left, value on the right.
    _SUMMARY_STYLE = """
        QLabel#SummaryName {
            color: #6B7A85; font-size: 12px; font-weight: 600;
            letter-spacing: 0.2px; background: transparent;
        }
        QLabel#SummaryValue {
            color: #1F2A33; font-size: 14px; font-weight: 500;
            background: transparent;
        }
        QFrame#SummaryRow {
            border: none;
            border-bottom: 1px solid #EAF0F3;
        }
    """

    def __init__(self, episode: dict, parent=None):
        super().__init__(parent)
        self.episode = episode or {}
        # Set to True when the user confirms deletion / requests a modify; the
        # caller acts on it after exec() returns.
        self.delete_requested = False
        self.modify_requested = False
        self.init_ui()

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        self.setWindowTitle("Channel details")
        self.setModal(True)
        self.resize(660, 660)
        self.setMinimumSize(420, 320)

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

        # Resize handle pinned to the card's bottom-right corner (frameless
        # window has no native border). Positioned manually in resizeEvent so it
        # sits in the true corner, not inside the body padding.
        self._size_grip = QSizeGrip(self)
        self._size_grip.resize(self._size_grip.sizeHint())
        self._position_size_grip()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_size_grip()

    def _position_size_grip(self) -> None:
        grip = getattr(self, "_size_grip", None)
        if grip is None:
            return
        margin = 20  # matches the outer shadow margin around the card
        grip.move(
            self.width() - margin - grip.width(),
            self.height() - margin - grip.height(),
        )
        grip.raise_()

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("DialogHeader")
        header.setFixedHeight(80)

        layout = QVBoxLayout(header)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(2)

        title = QLabel(self._dialog_title())
        title.setObjectName("DialogTitle")

        layout.addWidget(title)
        return header

    def _dialog_title(self) -> str:
        data = self.episode.get("data", {})
        channel = (data.get("channel") or "").strip()
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
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        content = QWidget()
        content.setStyleSheet(self._SUMMARY_STYLE)
        form = QVBoxLayout(content)
        form.setContentsMargins(0, 0, 8, 0)
        form.setSpacing(0)

        for label, value in self._info_items():
            form.addWidget(self._build_row(label, value))

        form.addStretch(1)
        scroll.setWidget(content)
        body_layout.addWidget(scroll, 1)

        # Bottom action row: Modify, then a red Delete, beside Close.
        button_row = QHBoxLayout()
        button_row.addStretch(1)

        # Always enabled for now; finished-only gating to be added later.
        modify_btn = QPushButton("Modify")
        modify_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        modify_btn.setAutoDefault(False)
        modify_btn.clicked.connect(self._on_modify)
        button_row.addWidget(modify_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.setAutoDefault(False)
        delete_btn.setStyleSheet(
            "QPushButton { background: #E04134; color: #FFFFFF;"
            " border: 1px solid #C7392D; }"
            " QPushButton:hover { background: #C7392D; }"
            " QPushButton:pressed { background: #A82E24; }"
            " QPushButton:disabled { background: #E7BCB8; color: #F4E4E2;"
            " border: 1px solid #DFB0AB; }"
        )
        delete_btn.clicked.connect(self._on_delete)

        # Any bar is deletable for now. Restore the block below to re-enable the
        # "only finished tests can be deleted" gating (we'll come back to this):
        #
        #   status = (self.episode.get("status") or "").strip().lower()
        #   can_delete = status == "test finished"
        #   delete_btn.setEnabled(can_delete)
        #   # A disabled button gets no hover events, so its own tooltip never
        #   # shows. Hosting it in a container lets the hover fall through to the
        #   # parent, whose tooltip explains why deletion is blocked.
        #   if not can_delete:
        #       delete_holder.setToolTip(
        #           "Only finished tests can be deleted. Set this experiment's "
        #           "status to \"Test finished\" first."
        #       )
        delete_btn.setEnabled(True)

        delete_holder = QWidget()
        holder_layout = QHBoxLayout(delete_holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addWidget(delete_btn)

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.reject)

        button_row.addWidget(delete_holder)
        button_row.addWidget(close_btn)
        body_layout.addLayout(button_row)

        return body

    def _on_modify(self) -> None:
        """Flag a modify request and close; the caller opens the editor."""
        self.modify_requested = True
        self.accept()

    def _on_delete(self) -> None:
        """Confirm, then flag the delete and close (the caller does the work)."""
        confirm = QMessageBox.question(
            self,
            "Delete entry",
            "Are you sure you want to permanently delete this timeline entry?\n\n",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.delete_requested = True
            self.accept()

    def _build_row(self, label_text: str, value_text: str) -> QFrame:
        row = QFrame()
        row.setObjectName("SummaryRow")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 10, 2, 10)
        layout.setSpacing(16)

        name = QLabel(label_text)
        name.setObjectName("SummaryName")

        value = QLabel(value_text if value_text else "—")
        value.setObjectName("SummaryValue")
        # No wrap: long values extend and the scroll area shows a horizontal
        # scrollbar (matching the vertical one) instead of wrapping.
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

    # ----------------------------------------------------------------- Data
    def _info_items(self) -> list[tuple[str, str]]:
        """Return ``[(label, value), ...]`` describing the episode."""
        data = dict(self.episode.get("data", {}))

        items = []
        seen = set()
        for key, label in self._FIELDS:
            if key not in data:
                continue
            if key == "start_date":
                value = self._format_start(data)
            else:
                value = str(data.get(key) or "").strip()
            items.append((label, value))
            seen.add(key)
        # Append any unexpected extra keys, minus the internal ones.
        for key, value in data.items():
            if key in seen or key in self._HIDDEN_KEYS:
                continue
            items.append((key.replace("_", " ").capitalize(), str(value or "").strip()))
        return items

    @staticmethod
    def _format_start(data: dict) -> str:
        """Combine start_date + start_hour into 'YYYY-MM-DD HH:00'."""
        date = str(data.get("start_date") or "").strip()
        if not date:
            return ""
        hour = str(data.get("start_hour") or "").strip()
        try:
            return f"{date} {int(hour):02d}:00" if hour else date
        except ValueError:
            return date

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


