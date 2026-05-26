from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QDialogButtonBox,
    QLabel,
    QTableWidgetItem,
    QFrame,
    QScrollArea,
    QWidget,
    QGraphicsDropShadowEffect,
    QComboBox,
    QDateEdit,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QDate, pyqtSignal
from PyQt6.QtGui import QColor


# Custom QComboBox that passes wheel events to parent for scrolling
class ScrollableComboBox(QComboBox):
    def wheelEvent(self, event):
        # Pass wheel event to parent scroll area instead of handling it
        self.parent().wheelEvent(event)


# Custom QDateEdit that passes wheel events to parent for scrolling
class ScrollableDateEdit(QDateEdit):
    def wheelEvent(self, event):
        # Pass wheel event to parent scroll area instead of handling it
        self.parent().wheelEvent(event)

from src.gui.styles.dialog_styles import DIALOG_STYLE
from src.gui.widgets.field_types import FieldSpec, FieldType
from src.gui.widgets.pill_combo_box import PillComboBox


# Custom PillComboBox that passes wheel events to parent for scrolling
class ScrollablePillComboBox(PillComboBox):
    def wheelEvent(self, event):
        # Pass wheel event to parent scroll area instead of handling it
        self.parent().wheelEvent(event)


class EditRowDialog(QDialog):
    """Dialog for editing or adding a row in the Immersion Cells table"""

    # Signal emitted when row is saved with the updated row data
    row_saved = pyqtSignal(list)
    # Signal emitted when a new row is added (includes the mode flag)
    row_added = pyqtSignal(list)

    # Column name (case-insensitive) that identifies the channel.
    CHANNEL_COLUMN = "channel"

    def __init__(self, table, row, manager, parent=None, is_add_mode=False):
        super().__init__(parent)
        self.table = table
        self.row = row
        self.manager = manager
        self.columns = manager.get_column_names()
        self.input_fields = {}
        self.is_add_mode = is_add_mode

        # Resolve the channel column index + current value up front so we can
        # use it in the dialog title and lock the field (unless adding).
        self._channel_col = self._find_channel_column()
        self._channel_value = self._get_cell_text(self._channel_col) if self._channel_col is not None and not is_add_mode else ""

        self.init_ui()
        self.load_row_data()

    # ...existing code...

    # --------------------------------------------------------------- helpers
    def _find_channel_column(self):
        for idx, name in enumerate(self.columns):
            if name.strip().lower() == self.CHANNEL_COLUMN:
                return idx
        return None

    def _get_cell_text(self, column):
        item = self.table.item(self.row, column)
        return item.text() if item else ""

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        """Initialize the edit dialog UI"""
        title_text = self._dialog_title()
        self.setWindowTitle(title_text)
        self.setModal(True)
        self.resize(560, 560)

        # Frameless + translucent so we can render a rounded card with shadow
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(DIALOG_STYLE)

        # Outer layout adds padding so the drop shadow has room to render
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

        subtitle_text = self._dialog_subtitle()
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("DialogSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        return header

    def _dialog_title(self) -> str:
        if self.is_add_mode:
            return "Adding new channel"
        if self._channel_value:
            return f"Edit Channel {self._channel_value}"
        return f"Edit Row {self.row + 1}"

    def _dialog_subtitle(self) -> str:
        if self.is_add_mode:
            return "Fill in the fields below and click Save to create the new channel."
        return "Update the fields below and click Save to apply your changes."

    def _build_body(self) -> QFrame:
        body = QFrame()
        body.setObjectName("DialogBody")

        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(28, 26, 28, 22)
        body_layout.setSpacing(20)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        form_container = QWidget()
        form_layout = QVBoxLayout(form_container)
        form_layout.setContentsMargins(2, 8, 14, 8)
        form_layout.setSpacing(28)

        for column_name in self.columns:
            form_layout.addLayout(self._build_field(column_name))

        form_layout.addStretch(1)
        scroll.setWidget(form_container)
        body_layout.addWidget(scroll, 1)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = button_box.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setDefault(True)
            save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        button_box.accepted.connect(self.save_changes)
        button_box.rejected.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(button_box)
        body_layout.addLayout(button_row)

        return body

    def _build_field(self, column_name: str) -> QVBoxLayout:
        wrapper = QVBoxLayout()
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.setSpacing(8)

        spec = self._spec_for(column_name)
        is_channel = column_name.strip().lower() == self.CHANNEL_COLUMN
        # Channel is read-only in edit mode, but editable in add mode
        is_read_only = (spec.read_only or is_channel) and not self.is_add_mode

        label_text = column_name
        if is_read_only:
            label_text = f"{column_name}  🔒"

        label = QLabel(label_text)
        label.setObjectName("FieldLabel")

        editor = self._build_editor(spec, read_only=is_read_only)
        self.input_fields[column_name] = editor

        wrapper.addWidget(label)
        wrapper.addWidget(editor)
        return wrapper

    # -------------------------------------------------- Editor factory
    def _build_editor(self, spec: FieldSpec, read_only: bool) -> QWidget:
        """Create the right widget for a field based on its type."""
        if spec.field_type is FieldType.CHOICE:
            if spec.color_resolver is not None:
                combo = ScrollablePillComboBox(spec.color_resolver)
            else:
                combo = ScrollableComboBox()
            combo.setObjectName("ChoiceField")
            combo.setCursor(Qt.CursorShape.PointingHandCursor)
            combo.addItems(spec.choices)
            combo.setEnabled(not read_only)
            # Give popup items extra breathing room so the pills don't touch.
            view = combo.view()
            if view is not None:
                view.setSpacing(2)
            return combo

        if spec.field_type is FieldType.DATE:
            date_edit = ScrollableDateEdit()
            date_edit.setObjectName("DateField")
            date_edit.setCalendarPopup(True)
            date_edit.setDisplayFormat(spec.date_format)
            date_edit.setDate(QDate.currentDate())
            date_edit.setReadOnly(read_only)
            return date_edit

        # Default: plain text
        line = QLineEdit()
        line.setClearButtonEnabled(False)
        if read_only:
            line.setReadOnly(True)
            line.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            line.setProperty("readOnly", True)
            line.setPlaceholderText("")
        else:
            placeholder = spec.placeholder or f"Enter {spec.name.lower()}…"
            line.setPlaceholderText(placeholder)
        return line

    def _spec_for(self, column_name: str) -> FieldSpec:
        """Get the FieldSpec for a column, falling back to plain text."""
        getter = getattr(self.manager, "get_field_spec", None)
        if callable(getter):
            return getter(column_name)
        return FieldSpec(name=column_name, field_type=FieldType.TEXT)

    # ---------------------------------------------------------------- Data
    def load_row_data(self):
        """Load current row data into the input fields"""
        for column, column_name in enumerate(self.columns):
            item = self.table.item(self.row, column)
            field = self.input_fields.get(column_name)
            if field is None:
                continue
            text = item.text() if item else ""
            spec = self._spec_for(column_name)
            self._set_editor_value(field, spec, text)

    def save_changes(self):
        """Save changes back to the table and emit signal with row data"""
        # Build the row data from editor values
        row_data = []
        for column_name in self.columns:
            editor = self.input_fields.get(column_name)
            if editor is None:
                row_data.append("")
                continue
            spec = self._spec_for(column_name)
            value = self._read_editor_value(editor, spec)
            row_data.append(value)

            # Also update the table
            column = self.columns.index(column_name)
            item = QTableWidgetItem(value)
            self.table.setItem(self.row, column, item)

        # In add mode, validate that the channel doesn't already exist
        if self.is_add_mode:
            channel_value = row_data[self._channel_col] if self._channel_col is not None else ""
            if not channel_value:
                QMessageBox.warning(
                    self,
                    "Invalid Channel",
                    "Channel cannot be empty. Please enter a channel name.",
                )
                return

            # Validate channel format: number-dash-number (e.g., "1-1")
            if not self._is_valid_channel_format(channel_value):
                QMessageBox.warning(
                    self,
                    "Invalid Channel Format",
                    f"Channel '{channel_value}' is invalid. Format must be: number-number (e.g., '1-1')",
                )
                return

            # Check if channel already exists
            existing_cell = self.manager.get_cell_by_channel(channel_value)
            if existing_cell:
                QMessageBox.warning(
                    self,
                    "Channel Already Exists",
                    f"A channel with name '{channel_value}' already exists. Please choose a different name.",
                )
                return

            # Emit the add signal instead
            self.row_added.emit(row_data)
        else:
            # Emit signal with the row data for the parent to handle persistence
            self.row_saved.emit(row_data)

        self.accept()

    # ---------------------------------------------- Validation
    @staticmethod
    def _is_valid_channel_format(channel: str) -> bool:
        """Validate channel format: number-dash-number (e.g., '1-1')."""
        import re
        pattern = r"^\d+-\d+$"
        return bool(re.match(pattern, channel))

    # ---------------------------------------------- Editor read / write
    @staticmethod
    def _set_editor_value(editor: QWidget, spec: FieldSpec, text: str) -> None:
        if isinstance(editor, QComboBox):
            idx = editor.findText(text, Qt.MatchFlag.MatchFixedString)
            if idx < 0 and text:
                # Preserve legacy values that aren't in the enum so we don't
                # silently overwrite them.
                editor.addItem(text)
                idx = editor.findText(text, Qt.MatchFlag.MatchFixedString)
            editor.setCurrentIndex(max(idx, 0))
            return

        if isinstance(editor, QDateEdit):
            qdate = QDate.fromString(text, spec.date_format)
            if not qdate.isValid():
                qdate = QDate.currentDate()
            editor.setDate(qdate)
            return

        if isinstance(editor, QLineEdit):
            editor.setText(text)
            editor.home(False)
            editor.update()

    @staticmethod
    def _read_editor_value(editor: QWidget, spec: FieldSpec) -> str:
        if isinstance(editor, QComboBox):
            return editor.currentText()
        if isinstance(editor, QDateEdit):
            return editor.date().toString(spec.date_format)
        if isinstance(editor, QLineEdit):
            return editor.text()
        return ""

    # ---------------------------------------------------- Window dragging
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        super().mouseMoveEvent(event)
