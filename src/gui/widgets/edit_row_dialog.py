from dataclasses import replace

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
    QDateTimeEdit,
    QAbstractSpinBox,
    QPushButton,
    QMessageBox,
    QTimeEdit,
    QTextEdit,
)
from PyQt6.QtCore import Qt, QDate, QTime, QEvent, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap, QIcon


# Custom QComboBox that passes wheel events to parent for scrolling
class ScrollableComboBox(QComboBox):
    def wheelEvent(self, event):
        # Pass wheel event to parent scroll area instead of handling it
        self.parent().wheelEvent(event)


class ProjectComboBox(ScrollableComboBox):
    """Dropdown for the Project ID field with a clearly visible arrow.

    A "▾" glyph is overlaid on the right so it's obvious the field is a
    dropdown. The glyph is transparent to mouse events, so clicking it still
    opens the popup like a normal combo box.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._arrow = QLabel("\u25BE", self)  # ▾
        self._arrow.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._arrow.setStyleSheet(
            "background: transparent; color: #4A5A66; font-size: 13px;"
            " border: none;"
        )
        self._arrow.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        margin = 12
        self._arrow.move(
            self.width() - self._arrow.width() - margin,
            (self.height() - self._arrow.height()) // 2,
        )


class CalendarTimeEdit(QTimeEdit):
    """Time field that can only be changed through direct input or spinner buttons.

    Scrolling does not change the time value. The display format is ``HH:00``,
    so the minutes are a fixed literal the user can't edit; clicking often
    landed the cursor there, making the hours feel uneditable. We always snap
    the cursor onto the hour section on focus and click so typing / the arrows
    just work.
    """

    def _select_hours(self) -> None:
        self.setSelectedSection(QDateTimeEdit.Section.HourSection)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._select_hours()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        # Override wherever the click landed (e.g. the fixed ":00") so the
        # editable hour section is the one selected.
        self._select_hours()

    def wheelEvent(self, event):
        # Pass wheel event to parent scroll area instead of changing the time.
        parent = self.parent()
        if parent is not None:
            parent.wheelEvent(event)


class CalendarDateEdit(QDateEdit):
    """Date field that can only be changed through the calendar popup.

    The date cannot be typed or edited by clicking around inside the field.
    A calendar icon on the right opens the popup where the user picks a date.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        # Hide the up/down spin arrows; the date is chosen via the calendar.
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        # Block direct editing: the embedded line edit is read-only, so the
        # user can't type or change individual date sections by clicking.
        line_edit = self.lineEdit()
        if line_edit is not None:
            line_edit.setReadOnly(True)
            line_edit.setCursor(Qt.CursorShape.PointingHandCursor)

        # Calendar icon overlay placed on top of the real drop-down button.
        # It is transparent to mouse events, so clicks fall through to the
        # button underneath, which opens the calendar popup.
        self._icon = QLabel("\U0001F4C5", self)  # 📅
        self._icon.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._icon.setStyleSheet(
            "background: transparent; font-size: 15px; border: none;"
        )
        self._icon.adjustSize()

    def set_calendar_enabled(self, enabled: bool) -> None:
        """Enable/disable the calendar popup (used for locked fields)."""
        self.setEnabled(enabled)
        self._icon.setVisible(enabled)

    def wheelEvent(self, event):
        # Pass wheel event to parent scroll area instead of changing the date.
        parent = self.parent()
        if parent is not None:
            parent.wheelEvent(event)

    def keyPressEvent(self, event):
        # Ignore keyboard input so arrow keys / typing can't change the date.
        event.ignore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        margin = 10
        self._icon.move(
            self.width() - self._icon.width() - margin,
            (self.height() - self._icon.height()) // 2,
        )


class OptionalDateEdit(CalendarDateEdit):
    """Calendar date picker that can also be empty ("not set").

    Emptiness is represented with Qt's special-value trick: at ``minimumDate``
    the field shows placeholder text instead of a date. Delete/Backspace clears
    it back to "not set"; picking a day from the calendar sets it.
    """

    UNSET = QDate(1900, 1, 1)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumDate(self.UNSET)
        self.setSpecialValueText("— not set —")
        self.setDate(self.UNSET)
        cal = self.calendarWidget()
        # When unset the value is 1900, so the popup would open on Jan 1900.
        # Catch the calendar's show and jump it to the current month instead.
        cal.installEventFilter(self)
        # A planned end can't be in the past: snap a past pick up to today. Only
        # user picks fire these, so loading an existing old value is unaffected.
        cal.clicked.connect(self._reject_past)
        cal.activated.connect(self._reject_past)

    def _reject_past(self, qdate) -> None:
        if qdate < QDate.currentDate():
            self.setDate(QDate.currentDate())

    def eventFilter(self, obj, event):
        if (
            obj is self.calendarWidget()
            and event.type() == QEvent.Type.Show
            and not self.is_set()
        ):
            today = QDate.currentDate()
            obj.setCurrentPage(today.year(), today.month())
        return super().eventFilter(obj, event)

    def is_set(self) -> bool:
        return self.date() != self.UNSET

    def clear_date(self) -> None:
        self.setDate(self.UNSET)

    def keyPressEvent(self, event):
        # Allow clearing; otherwise stay read-only (like CalendarDateEdit).
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.clear_date()
            event.accept()
            return
        event.ignore()


class CalendarDateTimeEdit(QWidget):
    """Date + Time (hours only) picker widget.

    Combines a calendar date picker with an hours spinner.
    Minutes are not included - only hours are editable.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        """Build the date and time selector layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Date picker
        self.date_edit = CalendarDateEdit()
        self.date_edit.setObjectName("DateField")
        layout.addWidget(self.date_edit, 2)  # Takes more space

        # Time label
        time_label = QLabel("Time:")
        time_label.setStyleSheet("background: transparent; font-size: 13px;")
        layout.addWidget(time_label, 0)

        # Time picker (hours only)
        self.time_edit = CalendarTimeEdit()
        self.time_edit.setDisplayFormat("HH:00")  # Show only hours, minutes fixed at 00
        self.time_edit.setObjectName("TimeField")
        layout.addWidget(self.time_edit, 1)

    def setDate(self, date: QDate):
        """Set the date part."""
        self.date_edit.setDate(date)

    def setHours(self, hours: int):
        """Set the hours part."""
        hours = max(0, min(23, hours))  # Clamp to 0-23
        self.time_edit.setTime(QTime(hours, 0, 0))

    def date(self) -> QDate:
        """Get the date part."""
        return self.date_edit.date()

    def hours(self) -> int:
        """Get the hours part."""
        return self.time_edit.time().hour()

    def setDisplayFormat(self, fmt: str):
        """Set the date display format."""
        self.date_edit.setDisplayFormat(fmt)

    def set_calendar_enabled(self, enabled: bool):
        """Enable/disable the date picker (used for locked fields)."""
        self.date_edit.set_calendar_enabled(enabled)
        self.time_edit.setEnabled(enabled)

    def setEnabled(self, enabled: bool):
        """Enable/disable the entire widget."""
        super().setEnabled(enabled)
        self.date_edit.setEnabled(enabled)
        self.time_edit.setEnabled(enabled)

from src.gui.styles.dialog_styles import DIALOG_STYLE
from src.gui.widgets.field_types import FieldSpec, FieldType
from src.gui.widgets.pill_combo_box import PillComboBox
from src.gui.widgets.projects_admin_dialog import ProjectsAdminDialog


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

    # Column name (case-insensitive) that uses the project dropdown + manager.
    PROJECT_COLUMN = "project id"

    # Default values (by lower-cased column name) applied when a field is empty.
    DEFAULT_VALUES = {}

    # Statuses that free the cell: saving clears the row except the kept fields.
    CLEARING_STATUSES = ("available", "in repair")
    # Fields (lower-cased) that survive the clear.
    KEPT_ON_CLEAR = ("channel", "status", "added water by timing", "separator")
    # Extra fields kept for a specific clearing status. In repair keeps Comments
    # so the repair can be documented; Available still fully frees the cell.
    EXTRA_KEPT_ON_CLEAR = {"in repair": ("comments",)}

    def __init__(self, table, row, manager, parent=None, is_add_mode=False,
                 on_project_removed=None, on_project_renamed=None,
                 status_choices=None):
        super().__init__(parent)
        self.table = table
        self.row = row
        self.manager = manager
        # When set, overrides the Status dropdown options (e.g. the Station
        # Summary editor hides cell-only states like Available / In repair).
        self._status_choices = status_choices
        self.columns = manager.get_column_names()
        self.input_fields = {}
        self.is_add_mode = is_add_mode
        # Callback invoked (with the project name) when a project is removed
        # from the manage-projects window, so the deletion can cascade.
        self.on_project_removed = on_project_removed
        # Callback invoked (with old and new name) when a project is renamed,
        # so the rename can cascade to channels and the station history.
        self.on_project_renamed = on_project_renamed
        self.status_warning_label = None  # Will hold the red warning "!"
        self.reset_info_banner = None  # Will hold the reset mode info banner
        self.reset_info_message = None  # The banner's message label (dynamic text)
        self.initial_status = ""  # Track initial status to detect changes

        # Store the original data filename so we can detect changes
        self.original_data_filename = ""

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

    def _create_reset_info_banner(self) -> QFrame:
        """Create an info banner shown when Status is set to a clearing status."""
        banner = QFrame()
        banner.setObjectName("ResetInfoBanner")
        banner.setStyleSheet("""
            QFrame#ResetInfoBanner {
                background-color: #E3F2FD;
                border-radius: 8px;
                border-left: 4px solid #2196F3;
                padding: 12px 16px;
            }
        """)
        
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)
        
        # Info icon
        info_icon = QLabel("ℹ️")
        info_icon.setStyleSheet("font-size: 16px; color: #2196F3;")
        layout.addWidget(info_icon)
        
        # Message (text is set per target status in _on_status_changed).
        message = QLabel(self._reset_banner_text("available"))
        message.setStyleSheet("color: #1565C0; font-size: 12px; line-height: 1.4;")
        message.setWordWrap(True)
        self.reset_info_message = message
        layout.addWidget(message, 1)
        
        return banner

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

        # Build all fields and track where to insert banner (after Status field)
        status_field_index = None
        for col_idx, column_name in enumerate(self.columns):
            # Skip "Start hour" - it's managed by the date picker, not shown as a separate field
            if column_name.strip().lower() == "start hour":
                continue

            # Track Status field position
            if column_name.strip().lower() == "status":
                status_field_index = form_layout.count()

            form_layout.addLayout(self._build_field(column_name))

        form_layout.addStretch(1)

        # Create and insert the reset info banner after Status field
        if status_field_index is not None:
            self.reset_info_banner = self._create_reset_info_banner()
            self.reset_info_banner.setVisible(False)  # Hidden by default
            form_layout.insertWidget(status_field_index + 1, self.reset_info_banner)

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

        # For Status field, add a warning label and connect change signal
        if column_name.strip().lower() == "status" and isinstance(editor, QComboBox):
            label_row = QHBoxLayout()
            label_row.setContentsMargins(0, 0, 0, 0)
            label_row.setSpacing(6)
            label_row.addWidget(label)

            wrapper.addLayout(label_row)
            editor.currentTextChanged.connect(self._on_status_changed)
        else:
            wrapper.addWidget(label)

        # The Project ID dropdown gets a "manage" button beside it that opens
        # the projects administration window.
        is_project = column_name.strip().lower() == self.PROJECT_COLUMN
        if is_project and isinstance(editor, QComboBox) and not is_read_only:
            # Distinct object name so it renders with a visible dropdown arrow.
            editor.setObjectName("ProjectField")

            editor_row = QHBoxLayout()
            editor_row.setContentsMargins(0, 0, 0, 0)
            editor_row.setSpacing(8)
            editor_row.addWidget(editor, 1)

            manage_btn = QPushButton("Manage projects")
            manage_btn.setToolTip("Add or remove projects")
            manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            # Don't let this button grab the Enter key — in a dialog every
            # QPushButton is an auto-default by default, which made pressing
            # Enter open the projects window instead of saving. Enter should
            # fall through to the dialog's default Save button.
            manage_btn.setAutoDefault(False)
            manage_btn.clicked.connect(
                lambda _checked=False, combo=editor: self._open_projects_admin(combo)
            )
            editor_row.addWidget(manage_btn)
            wrapper.addLayout(editor_row)
        elif isinstance(editor, OptionalDateEdit) and not is_read_only:
            # Optional date: a Clear button beside it resets it to "not set".
            editor_row = QHBoxLayout()
            editor_row.setContentsMargins(0, 0, 0, 0)
            editor_row.setSpacing(8)
            editor_row.addWidget(editor, 1)

            clear_btn = QPushButton("Clear")
            clear_btn.setToolTip("Clear this date")
            clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            clear_btn.setAutoDefault(False)
            clear_btn.clicked.connect(
                lambda _checked=False, e=editor: e.clear_date()
            )
            editor_row.addWidget(clear_btn)
            wrapper.addLayout(editor_row)
        else:
            wrapper.addWidget(editor)
        return wrapper

    # -------------------------------------------------- Editor factory
    def _build_editor(self, spec: FieldSpec, read_only: bool) -> QWidget:
        """Create the right widget for a field based on its type."""
        if spec.field_type is FieldType.CHOICE:
            if spec.color_resolver is not None:
                combo = ScrollablePillComboBox(spec.color_resolver)
            elif spec.name.strip().lower() == self.PROJECT_COLUMN:
                # Project dropdown with a visible arrow indicator.
                combo = ProjectComboBox()
                combo.setObjectName("ProjectField")
                combo.setCursor(Qt.CursorShape.PointingHandCursor)
                combo.addItems(spec.choices)
                combo.setEnabled(not read_only)
                self._apply_project_colors(combo)
                return combo
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
            date_time_edit = CalendarDateTimeEdit()
            date_time_edit.setObjectName("DateTimeField")
            date_time_edit.setDisplayFormat(spec.date_format)
            date_time_edit.setDate(QDate.currentDate())
            date_time_edit.setHours(0)
            # Locked fields disable the calendar popup entirely.
            date_time_edit.set_calendar_enabled(not read_only)
            return date_time_edit

        if spec.field_type is FieldType.DATE_ONLY:
            date_edit = OptionalDateEdit()
            date_edit.setObjectName("DateField")
            date_edit.setDisplayFormat(spec.date_format)
            date_edit.set_calendar_enabled(not read_only)
            return date_edit

        # Comments get a multi-line, growable box. A single-line QLineEdit hid
        # every line past the first as the user typed; QTextEdit shows them and
        # can be resized. Tab moves to the next field instead of inserting a tab.
        if spec.name.strip().lower() == "comments":
            text_edit = QTextEdit()
            text_edit.setObjectName("CommentsField")
            text_edit.setMinimumHeight(90)
            text_edit.setTabChangesFocus(True)
            if read_only:
                text_edit.setReadOnly(True)
                text_edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            else:
                text_edit.setPlaceholderText(spec.placeholder or "Enter comments…")
            return text_edit

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
        spec = (
            getter(column_name) if callable(getter)
            else FieldSpec(name=column_name, field_type=FieldType.TEXT)
        )
        if (self._status_choices is not None
                and column_name.strip().lower() == "status"):
            spec = replace(spec, choices=list(self._status_choices))
        return spec

    # -------------------------------------------------- Project colors
    @staticmethod
    def _color_icon(hex_color: str, size: int = 12) -> QIcon:
        """Return a small square color swatch icon for ``hex_color``."""
        pix = QPixmap(size, size)
        pix.fill(QColor(hex_color))
        return QIcon(pix)

    def _apply_project_colors(self, combo: QComboBox) -> None:
        """Show each project's color as a swatch next to its name."""
        getter = getattr(self.manager, "get_projects_manager", None)
        if not callable(getter):
            return
        colors = getter().get_project_colors()
        for i in range(combo.count()):
            name = combo.itemText(i)
            hex_color = colors.get(name)
            if hex_color:
                combo.setItemIcon(i, self._color_icon(hex_color))
            else:
                combo.setItemIcon(i, QIcon())  # empty / "no project"

    # ---------------------------------------------------------------- Data
    def load_row_data(self):
        """Load current row data into the input fields"""
        for column, column_name in enumerate(self.columns):
            item = self.table.item(self.row, column)
            field = self.input_fields.get(column_name)
            if field is None:
                continue
            text = item.text() if item else ""
            # Fall back to a default value when the stored cell is empty.
            if not text.strip():
                text = self.DEFAULT_VALUES.get(column_name.strip().lower(), text)
            spec = self._spec_for(column_name)
            self._set_editor_value(field, spec, text)

            # Store original data filename
            if column_name.strip().lower() == "data filename":
                self.original_data_filename = text.strip()
            
            # Store initial status for banner logic
            if column_name.strip().lower() == "status":
                self.initial_status = text.strip().lower()

        try:
            # Find the columns case-insensitively
            start_hour_col = None
            start_date_col = None
            for idx, col_name in enumerate(self.columns):
                if col_name.strip().lower() == "start hour":
                    start_hour_col = idx
                elif col_name.strip().lower() == "start date":
                    start_date_col = idx

            if start_hour_col is not None:
                start_hour_item = self.table.item(self.row, start_hour_col)
                start_hour_text = start_hour_item.text() if start_hour_item else ""

                if start_hour_text.strip():
                    date_field = self.input_fields.get("Start date")
                    if isinstance(date_field, CalendarDateTimeEdit):
                        try:
                            hours = int(start_hour_text.strip())
                            date_field.setHours(hours)
                        except (ValueError, AttributeError):
                            pass
        except (ValueError, IndexError):
            # Columns don't exist, skip
            pass

    def _kept_on_clear(self, status: str) -> tuple:
        """Fields (lower-cased) that survive the clear for ``status``."""
        extra = self.EXTRA_KEPT_ON_CLEAR.get(status.strip().lower(), ())
        return self.KEPT_ON_CLEAR + extra

    def _reset_banner_text(self, status: str) -> str:
        """Banner message listing the fields kept when freeing the cell."""
        kept = "Channel, Added water, and Separator"
        if status.strip().lower() == "in repair":
            kept = "Channel, Added water, Separator, and Comments"
        return (
            "<b>This status frees the cell</b><br>"
            f"Saving will clear this cell’s fields (except {kept}). "
            "Choose a different status instead if you want to keep the data."
        )

    def _on_status_changed(self, status_value: str):
        """Handle status change to show/hide the warning indicator and enable/disable fields.
        
        Banner only shows when actively switching TO Available (not when it's already set).
        """
        new_status = status_value.strip().lower()
        if self.status_warning_label is not None:
            self.status_warning_label.setHidden(
                new_status not in self.CLEARING_STATUSES
            )

        # Show the banner when switching TO a clearing status from a non-clearing
        # one (not if the cell was already a clearing status on load).
        if self.reset_info_banner is not None:
            should_show_banner = (
                new_status in self.CLEARING_STATUSES
                and self.initial_status not in self.CLEARING_STATUSES
            )
            if should_show_banner and self.reset_info_message is not None:
                self.reset_info_message.setText(self._reset_banner_text(new_status))
            self.reset_info_banner.setVisible(should_show_banner)

    def _open_projects_admin(self, combo: QComboBox) -> None:
        """Open the projects admin window and refresh the dropdown afterwards."""
        getter = getattr(self.manager, "get_projects_manager", None)
        if not callable(getter):
            return
        projects_manager = getter()

        # Remember the project list and current selection before any edits so we
        # can tell whether the selected project was removed.
        before = set(projects_manager.get_projects())
        current = combo.currentText()

        dialog = ProjectsAdminDialog(
            projects_manager, self, on_remove=self.on_project_removed,
            on_rename=self.on_project_renamed,
        )
        dialog.exec()

        # Rebuild the dropdown from the (possibly changed) project list.
        after = projects_manager.get_projects()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")  # keep an empty option so "no project" is possible
        combo.addItems(after)

        if current in after:
            # Still a valid project: keep the selection.
            target = current
        elif current and current not in before:
            # A legacy value that was never a managed project: preserve it so we
            # don't silently overwrite the cell's existing value.
            combo.addItem(current)
            target = current
        else:
            # The selected project was removed (or selection was empty): clear.
            target = ""

        # Re-apply color swatches for the rebuilt items (colors may have changed).
        self._apply_project_colors(combo)

        idx = combo.findText(target, Qt.MatchFlag.MatchFixedString)
        combo.setCurrentIndex(max(idx, 0))
        combo.blockSignals(False)

    def save_changes(self):
        """Save changes back to the table and emit signal with row data"""
        # Build the row data from editor values. Don't touch the table yet —
        # the cells are only written once every validation below has passed, so
        # a blocked save can't leave data sitting in the table that the DB never
        # received (which would then vanish on the next reload/restart).
        row_data = []
        for column_name in self.columns:
            # Handle "Start hour" specially - extract from date picker
            if column_name.strip().lower() == "start hour":
                date_field = self.input_fields.get("Start date")
                if isinstance(date_field, CalendarDateTimeEdit):
                    row_data.append(str(date_field.hours()))
                else:
                    row_data.append("")
                continue

            editor = self.input_fields.get(column_name)
            if editor is None:
                row_data.append("")
                continue
            spec = self._spec_for(column_name)
            row_data.append(self._read_editor_value(editor, spec))

        # Validate: if status is not "available" or "in repair", data filename is required
        status_col = None
        data_filename_col = None

        try:
            status_col = self.columns.index("Status")
        except ValueError:
            pass

        try:
            data_filename_col = self.columns.index("Data filename")
        except ValueError:
            pass

        # Available / In repair free the cell: the clearable fields are emptied on
        # save by the clear step below. Guard only the case where the cell was
        # *already* a clearing status on open and the user has since typed new
        # data but left that status — auto-clearing would silently wipe it, so
        # block and ask them to pick a data-keeping status (or clear it themselves).
        new_status = row_data[status_col].strip().lower() if status_col is not None else ""
        if (status_col is not None
                and new_status in self.CLEARING_STATUSES
                and self.initial_status == new_status):
            # Only real typed data should block; ignore the kept fields and the
            # always-populated date/hour/duration (which can't be emptied).
            ignore_cols = self._kept_on_clear(new_status) + ("start date", "start hour", "duration")
            has_data = any(
                row_data[idx].strip()
                for idx, name in enumerate(self.columns)
                if name.strip().lower() not in ignore_cols
            )
            if has_data:
                QMessageBox.warning(
                    self,
                    "Change the status to save",
                    f"This row still has data but its status is "
                    f"'{row_data[status_col]}'.\n\n"
                    "Change the status to one that keeps data, or clear the other "
                    "fields to free the cell.",
                )
                return

        if status_col is not None and data_filename_col is not None:
            status_value = row_data[status_col].strip().lower()
            filename_value = row_data[data_filename_col].strip()

            # If status is not "available" and not "in repair", data filename is required
            if status_value not in ["available", "in repair"] and not filename_value:
                QMessageBox.warning(
                    self,
                    "Data Filename Required",
                    f"Status '{row_data[status_col]}' requires a Data filename. Please enter one before saving.",
                )
                return

            # data_filename is a unique key: block a new/changed name that another
            # experiment already uses. (Unchanged name = same experiment, skipped.)
            checker = getattr(self.manager, "filename_exists", None)
            if (filename_value
                    and filename_value != self.original_data_filename
                    and callable(checker) and checker(filename_value)):
                QMessageBox.warning(
                    self,
                    "Data filename already used",
                    f"The data filename '{filename_value}' is already used by "
                    "another experiment.\n\nData filenames must be unique. Please "
                    "choose a different name.",
                )
                return

            # Warn if filename is being changed
            if self.original_data_filename and filename_value and filename_value != self.original_data_filename:
                # Filename was changed - ask for confirmation
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("Rename Filename?")
                msg_box.setText(
                    "Are you trying to rename the filename or starting a new experiment?\n\n"
                    "If you want to start a new experiment, you should set the channel status to 'Available' first.\n\n"
                    "Click 'Yes, rename' to update the existing experiment's filename, or 'Cancel' to go back."
                )

                # Add custom buttons
                rename_btn = msg_box.addButton("Yes, rename", QMessageBox.ButtonRole.AcceptRole)
                cancel_btn = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)

                msg_box.exec()

                if msg_box.clickedButton() == cancel_btn:
                    return
                # If Yes, proceed with the save

        # Available / In repair free the cell: clear every field except the kept ones.
        if (status_col is not None
                and row_data[status_col].strip().lower() in self.CLEARING_STATUSES):
            kept = self._kept_on_clear(row_data[status_col])
            for column_idx, column_name in enumerate(self.columns):
                if column_name.strip().lower() not in kept:
                    row_data[column_idx] = ""

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

        # Every validation passed — now commit the values into the table.
        for column_idx in range(len(self.columns)):
            self.table.setItem(
                self.row, column_idx, QTableWidgetItem(row_data[column_idx])
            )

        if self.is_add_mode:
            # Emit the add signal instead
            self.row_added.emit(row_data)
        else:
            # Store original data filename in row_data for tracking
            # (used by station_summary_manager to know if filename changed)
            if self.original_data_filename:
                row_data.append(self.original_data_filename)
            else:
                row_data.append("")  # Append empty string if no original filename

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

        if isinstance(editor, CalendarDateTimeEdit):
            # Parse date and optional time from text
            # Format: "yyyy-MM-dd" or "yyyy-MM-dd HH:00"
            parts = text.strip().split()
            date_part = parts[0] if parts else text
            time_part = parts[1] if len(parts) > 1 else "00:00"
            
            qdate = QDate.fromString(date_part, spec.date_format)
            if not qdate.isValid():
                qdate = QDate.currentDate()
            editor.setDate(qdate)
            
            # Parse hours from time part (format: "HH:00")
            try:
                hours = int(time_part.split(":")[0])
                editor.setHours(hours)
            except (ValueError, IndexError):
                editor.setHours(0)
            return

        if isinstance(editor, OptionalDateEdit):
            qdate = QDate.fromString(text.strip(), spec.date_format)
            editor.setDate(qdate if qdate.isValid() else editor.UNSET)
            return

        if isinstance(editor, QDateEdit):
            qdate = QDate.fromString(text, spec.date_format)
            if not qdate.isValid():
                qdate = QDate.currentDate()
            editor.setDate(qdate)
            return

        if isinstance(editor, QTextEdit):
            editor.setPlainText(text)
            return

        if isinstance(editor, QLineEdit):
            editor.setText(text)
            editor.home(False)
            editor.update()

    @staticmethod
    def _read_editor_value(editor: QWidget, spec: FieldSpec) -> str:
        if isinstance(editor, QComboBox):
            return editor.currentText()
        if isinstance(editor, CalendarDateTimeEdit):
            # Return only the date part for storage (hours are not persisted to CSV)
            return editor.date().toString(spec.date_format)
        if isinstance(editor, OptionalDateEdit):
            return editor.date().toString(spec.date_format) if editor.is_set() else ""
        if isinstance(editor, QDateEdit):
            return editor.date().toString(spec.date_format)
        if isinstance(editor, QTextEdit):
            return editor.toPlainText()
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
