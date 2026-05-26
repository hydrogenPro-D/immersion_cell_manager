from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QFrame,
    QLabel,
    QLineEdit,
    QSpacerItem,
    QSizePolicy,
    QGraphicsDropShadowEffect,
    QMessageBox,
    QTableWidgetItem,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from src.data.immersion_cells_manager import ImmersionCellsManager
from src.gui.widgets.edit_row_dialog import EditRowDialog
from src.gui.widgets.data_table_widget import DataTableWidget
from src.gui.widgets.confirm_dialog import ConfirmDialog
from src.gui.styles.tab_styles import TAB_STYLE


class ImmersionCellsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.manager = ImmersionCellsManager()
        self.init_ui()
        self.load_data()
        self._refresh_status()

    # ----------------------------------------------------------------- UI
    def init_ui(self):
        """Initialize the Immersion Cells tab UI"""
        self.setObjectName("TabRoot")
        self.setStyleSheet(TAB_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())

        # Data table
        self.table = DataTableWidget(self.manager)
        self.table.doubleClicked.connect(self.on_row_double_clicked)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self.table, 1)

        root.addLayout(self._build_footer())

    # ------------------------------------------------------------ Header
    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("PageHeader")
        header.setFixedHeight(70)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title = QLabel("Immersion Cells")
        title.setObjectName("PageTitle")

        text_col.addWidget(title)
        layout.addLayout(text_col, 1)

        self.count_badge = QLabel("0 cells")
        self.count_badge.setObjectName("PageBadge")
        self.count_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.count_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        # Subtle elevation
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(63, 163, 163, 90))
        header.setGraphicsEffect(shadow)

        return header

    # ----------------------------------------------------------- Toolbar
    def _build_toolbar(self) -> QFrame:
        toolbar = QFrame()
        toolbar.setObjectName("Toolbar")

        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        search_label = QLabel("🔍")
        search_label.setStyleSheet("background: transparent; font-size: 14px;")

        self.search_input = QLineEdit()
        self.search_input.setObjectName("SearchInput")
        self.search_input.setPlaceholderText("Search cells by channel, owner, status…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._apply_filter)

        layout.addWidget(search_label)
        layout.addWidget(self.search_input, 1)

        layout.addSpacerItem(
            QSpacerItem(12, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        )

        # Action buttons live in the toolbar for a tighter, more modern feel
        self.add_button = QPushButton("＋  Add Immersion Cell")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self._on_add_clicked)

        self.remove_button = QPushButton("🗑  Remove Selected Immersion Cell")
        self.remove_button.setObjectName("DangerButton")
        self.remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self._on_remove_clicked)

        layout.addWidget(self.add_button)
        layout.addWidget(self.remove_button)

        # Subtle shadow for the toolbar card
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(20, 50, 70, 35))
        toolbar.setGraphicsEffect(shadow)

        return toolbar

    # ------------------------------------------------------------ Footer
    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setContentsMargins(4, 0, 4, 0)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("StatusLabel")

        hint = QLabel("Double-click a row to edit")
        hint.setObjectName("StatusLabel")

        footer.addWidget(self.status_label)
        footer.addStretch(1)
        footer.addWidget(hint)
        return footer

    # ----------------------------------------------------------- Data ops
    def load_data(self):
        """Load data from the manager and populate the table"""
        try:
            table_data = self.manager.get_table_data()
            for row_data in table_data:
                self.add_row(row_data)
        except Exception as e:
            print(f"Error loading data: {e}")

    def on_row_double_clicked(self, index):
        """Handle double-click on a row to edit it"""
        self.open_edit_dialog(index.row())

    def open_edit_dialog(self, row):
        """Open a dialog to edit row values"""
        dialog = EditRowDialog(self.table, row, self.manager, self)
        dialog.row_saved.connect(self._on_row_saved)
        dialog.exec()
        self._refresh_status()

    def add_row(self, data):
        """Add a row to the table"""
        self.table.add_row(data)
        self._refresh_status()

    def _on_row_saved(self, row_data: list):
        """Callback when a row is saved from the edit dialog"""
        try:
            self.manager.update_row_by_channel(row_data)
            # Re-sort if a sort is currently active
            self.table.resort_if_needed()
        except Exception as e:
            print(f"Error saving row to JSON: {e}")

    def _on_add_clicked(self):
        """Handle add button click - open dialog to add new immersion cell"""
        # Create a new empty row in the table
        row_position = self.table.rowCount()
        self.table.insertRow(row_position)

        # Initialize with empty values
        for column in range(self.table.columnCount()):
            item = QTableWidgetItem("")
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.table.setItem(row_position, column, item)

        # Open the dialog in add mode
        dialog = EditRowDialog(self.table, row_position, self.manager, self, is_add_mode=True)
        dialog.row_added.connect(self._on_row_added)
        dialog.exec()
        self._refresh_status()

    def _on_row_added(self, row_data: list):
        """Callback when a new row is added from the add dialog"""
        try:
            self.manager.add_new_row(row_data)
            # Re-sort if a sort is currently active
            self.table.resort_if_needed()
        except Exception as e:
            print(f"Error adding row to JSON: {e}")

    # -------------------------------------------------------- Interactions
    def _apply_filter(self, text: str):
        """Hide rows that don't match the search text (any column)."""
        needle = text.strip().lower()
        visible = 0
        for row in range(self.table.rowCount()):
            if not needle:
                match = True
            else:
                match = False
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item and needle in item.text().lower():
                        match = True
                        break
            self.table.setRowHidden(row, not match)
            if match:
                visible += 1
        self._refresh_status(visible_override=visible if needle else None)

    def _on_selection_changed(self):
        self.remove_button.setEnabled(bool(self.table.selectionModel().selectedRows()))

    def _on_remove_clicked(self):
        """Confirm with the user, then remove the currently selected row."""
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return

        row = selected[0].row()
        channel = self._channel_for_row(row) or f"Row {row + 1}"

        confirmed = ConfirmDialog.ask(
            self,
            title="Remove Immersion Cell",
            message=f"Are you sure you want to delete channel <b>{channel}</b>?",
            confirm_text="Yes, delete",
            cancel_text="Cancel",
            destructive=True,
        )
        if not confirmed:
            return

        try:
            # Delete from CSV first
            self.manager.delete_row_by_channel(channel)
            # Then remove from table UI
            self.table.removeRow(row)
        except Exception as e:
            print(f"Error deleting row from CSV: {e}")
            QMessageBox.critical(self, "Error", f"Failed to delete row: {e}")
            return

        self._refresh_status()

    def _channel_for_row(self, row: int) -> str:
        """Return the channel value for a given row, or '' if no channel column."""
        try:
            col = self.manager.get_column_names().index("Channel")
        except ValueError:
            return ""
        item = self.table.item(row, col)
        return item.text() if item else ""

    def _refresh_status(self, visible_override=None):
        total = self.table.rowCount()
        self.count_badge.setText(f"{total} cell{'s' if total != 1 else ''}")
        if visible_override is not None and visible_override != total:
            self.status_label.setText(f"Showing {visible_override} of {total} cells.")
        else:
            self.status_label.setText(f"{total} cell{'s' if total != 1 else ''} loaded.")
