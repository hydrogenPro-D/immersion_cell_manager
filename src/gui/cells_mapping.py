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

from src.gui.widgets.edit_row_dialog import EditRowDialog
from src.gui.widgets.data_table_widget import DataTableWidget
from src.gui.widgets.confirm_dialog import ConfirmDialog
from src.gui.widgets.zoom_control import ZoomControl
from src.gui.widgets.projects_admin_dialog import ProjectsAdminDialog
from src.gui.styles.tab_styles import TAB_STYLE


class CellsMapping(QWidget):
    def __init__(self, manager, on_channel_logged=None, on_project_removed=None,
                 on_project_renamed=None, on_channels_changed=None,
                 calibration_manager=None):
        super().__init__()
        self.manager = manager
        self.on_channel_logged = on_channel_logged
        self.on_project_removed = on_project_removed
        self.on_project_renamed = on_project_renamed
        # Called after a channel is added/deleted, so other tabs (e.g. Channel
        # Calibration) that mirror the cell list can refresh.
        self.on_channels_changed = on_channels_changed
        # Used to flag channels with a stale calibration + block them going In use.
        self.calibration_manager = calibration_manager
        self.init_ui()
        self.load_data()
        self._refresh_status()

    def _reload_from_external_changes(self) -> None:
        """Reload the table when external changes are detected."""
        self.reload_data()

    def reload_data(self) -> None:
        """Reload data from the manager (called when external changes are detected)."""
        try:
            # Remember the selected channel by value, not row index: the row
            # order can change after an external reload.
            selected_channel = None
            selected_rows = self.table.selectionModel().selectedRows()
            if selected_rows:
                selected_channel = self._channel_for_row(selected_rows[0].row())

            # Clear the table
            self.table.setRowCount(0)

            # Reload data
            self.load_data()
            self._refresh_status()

            # Re-apply the active search filter so a reload doesn't reveal rows
            # the user has filtered out.
            self._apply_filter(self.search_input.text())

            # Restore selection by matching the channel value.
            if selected_channel:
                self._select_row_by_channel(selected_channel)

        except Exception as e:
            print(f"Error reloading data from external changes: {e}")

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

        title = QLabel("Cells mapping")
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

        layout.addWidget(ZoomControl(lambda d: self.table.zoom_step(d)))

        layout.addSpacerItem(
            QSpacerItem(12, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        )

        # Action buttons live in the toolbar for a tighter, more modern feel
        manage_btn = QPushButton("Manage projects")
        manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        manage_btn.setFixedWidth(150)
        manage_btn.setStyleSheet(
            "QPushButton { background:#EBEFF2; color:#33404A; border:none;"
            " border-radius:6px; padding:8px 14px; font-weight:600; }"
            " QPushButton:hover { background:#DCE3E8; }"
        )
        manage_btn.clicked.connect(self._on_manage_projects)

        self.add_button = QPushButton("＋  Add Channel")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.setFixedWidth(150)
        self.add_button.clicked.connect(self._on_add_clicked)

        self.remove_button = QPushButton("🗑  Remove Selected Channel")
        self.remove_button.setObjectName("DangerButton")
        self.remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_button.setFixedWidth(220)
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self._on_remove_clicked)

        layout.addWidget(manage_btn)
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

    def _on_manage_projects(self):
        """Open the projects admin dialog, then refresh (density/color/rename)."""
        dialog = ProjectsAdminDialog(
            self.manager.get_projects_manager(), self,
            on_remove=self.on_project_removed,
            on_rename=self.on_project_renamed,
        )
        dialog.exec()
        self.reload_data()

    # ----------------------------------------------------------- Data ops
    def load_data(self):
        """Load data from the manager and populate the table"""
        try:
            # Refresh calibration flags before repopulating: the "!" on overdue
            # channels and the yellow row tint on awaiting-decision channels.
            if self.calibration_manager is not None:
                try:
                    self.table.set_stale_channels(
                        self.calibration_manager.get_stale_channels()
                    )
                    self.table.set_pending_channels(
                        self.calibration_manager.get_pending_channels()
                    )
                except Exception:
                    self.table.set_stale_channels(set())
                    self.table.set_pending_channels(set())
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
        channel = self._channel_for_row(row)
        stale = bool(channel) and channel in self.table._stale_channels
        has_cal = bool(channel) and self.calibration_manager is not None
        pending = has_cal and self.calibration_manager.is_channel_pending(channel)
        failed = has_cal and self.calibration_manager.is_channel_failed(channel)
        dialog = EditRowDialog(
            self.table, row, self.manager, self,
            on_project_removed=self.on_project_removed,
            on_project_renamed=self.on_project_renamed,
            calibration_stale=stale, calibration_pending=pending,
            calibration_failed=failed,
        )
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

            # Update the duration column for this row since it's calculated at runtime
            try:
                col_names = self.manager.get_column_names()
                duration_col_idx = col_names.index("Duration")
                channel_col_idx = col_names.index("Channel")
                channel = row_data[channel_col_idx]

                # Get the updated cell data from manager to recalculate duration
                cell = self.manager.get_cell_by_channel(channel)
                new_duration = self.manager._calculate_duration(cell)

                # Find the row in the table and update the duration column
                edited_row_idx = None
                for row_idx in range(self.table.rowCount()):
                    table_channel_item = self.table.item(row_idx, channel_col_idx)
                    if table_channel_item and table_channel_item.text() == channel:
                        duration_item = QTableWidgetItem(new_duration)
                        duration_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
                        self.table.setItem(row_idx, duration_col_idx, duration_item)
                        edited_row_idx = row_idx
                        break
            except (ValueError, IndexError):
                edited_row_idx = None

            # Re-sort if a sort is currently active
            self.table.resort_if_needed()

            # Re-center all items in the edited row after sorting
            if edited_row_idx is not None:
                col_names = self.manager.get_column_names()
                channel_col_idx = col_names.index("Channel")
                for row_idx in range(self.table.rowCount()):
                    table_channel_item = self.table.item(row_idx, channel_col_idx)
                    if table_channel_item and table_channel_item.text() == channel:
                        # Re-apply center alignment to all items in the row
                        for col_idx in range(self.table.columnCount()):
                            item = self.table.item(row_idx, col_idx)
                            if item:
                                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
                        # Scroll to keep it visible
                        self.table.scrollToItem(self.table.item(row_idx, 0), 
                                               self.table.ScrollHint.PositionAtCenter)
                        break

            # Log the channel usage via callback if available
            if self.on_channel_logged:
                col_names = self.manager.get_column_names()
                # row_data might have an extra element at the end: original_data_filename
                # Only map the columns that have column names
                row_dict = {col_names[i]: row_data[i] for i in range(min(len(col_names), len(row_data)))}

                # If there's an extra element, it's the original data filename
                original_data_filename = ""
                if len(row_data) > len(col_names):
                    original_data_filename = row_data[len(col_names)]

                # Pass original filename info for tracking
                if original_data_filename:
                    row_dict["__original_data_filename"] = original_data_filename

                channel = row_dict.get("Channel", "")
                if channel:
                    self.on_channel_logged(channel, row_dict)
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
        dialog = EditRowDialog(
            self.table, row_position, self.manager, self, is_add_mode=True,
            on_project_removed=self.on_project_removed,
            on_project_renamed=self.on_project_renamed,
        )
        dialog.row_added.connect(self._on_row_added)
        dialog.exec()
        self._refresh_status()

    def _on_row_added(self, row_data: list):
        """Callback when a new row is added from the add dialog"""
        try:
            self.manager.add_new_row(row_data)
            # Re-sort if a sort is currently active
            self.table.resort_if_needed()

            # Log the channel usage via callback if available
            if self.on_channel_logged:
                col_names = self.manager.get_column_names()
                row_dict = {col_names[i]: row_data[i] for i in range(len(col_names))}
                channel = row_dict.get("Channel", "")
                if channel:
                    self.on_channel_logged(channel, row_dict)
            # A new channel appeared — let mirror tabs refresh.
            if self.on_channels_changed:
                self.on_channels_changed()
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
        # A channel was removed — let mirror tabs refresh.
        if self.on_channels_changed:
            self.on_channels_changed()

    def _channel_for_row(self, row: int) -> str:
        """Return the channel value for a given row, or '' if no channel column."""
        try:
            col = self.manager.get_column_names().index("Channel")
        except ValueError:
            return ""
        item = self.table.item(row, col)
        return item.text() if item else ""

    def _select_row_by_channel(self, channel: str) -> None:
        """Select the row whose channel matches ``channel``, if one exists."""
        try:
            col = self.manager.get_column_names().index("Channel")
        except ValueError:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, col)
            if item and item.text() == channel:
                self.table.selectRow(row)
                return

    def _refresh_status(self, visible_override=None):
        total = self.table.rowCount()

        try:
            status_col_index = self.manager.get_column_names().index("Status")
        except (ValueError, IndexError):
            status_col_index = None

        # Operational = visible cells not "In repair". Count over the currently
        # visible rows (filtering hides non-matches) so the badge tracks the
        # filter, like the Station Summary badge.
        visible_total = 0
        in_repair_count = 0
        for row in range(total):
            if self.table.isRowHidden(row):
                continue
            visible_total += 1
            if status_col_index is not None:
                item = self.table.item(row, status_col_index)
                if item and item.text() == "In repair":
                    in_repair_count += 1
        active_count = visible_total - in_repair_count

        self.count_badge.setText(f"{active_count} operational cell{'s' if active_count != 1 else ''}")
        if visible_override is not None and visible_override != total:
            self.status_label.setText(f"Showing {visible_override} of {total} cells.")
        else:
            self.status_label.setText(f"{total} cell{'s' if total != 1 else ''} loaded.")
