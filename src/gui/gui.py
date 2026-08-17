import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QTabWidget, QMessageBox,
)
from PyQt6.QtCore import Qt
from src.data.db import DatabaseChangeNotifier, DatabaseError
from src.data.immersion_cells_manager import ImmersionCellsManager
from src.data.station_summary_manager import StationSummaryManager
from src.data.calibration_manager import CalibrationManager
from src.data.logbook_manager import LogbookManager
from src.data.projects_manager import invalidate_projects_cache
from src.gui.cells_mapping import CellsMapping
from src.gui.station_summary_gui import StationSummary
from src.gui.calibration_gui import CalibrationTab
from src.gui.logbook_gui import LogbookTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Create the managers once at the application level
        self.cells_manager = ImmersionCellsManager()
        self.summary_manager = StationSummaryManager()
        self.calibration_manager = CalibrationManager()
        self.logbook_manager = LogbookManager()
        self.init_ui()

        # Poll the database for external changes (other users) and refresh.
        self.change_notifier = DatabaseChangeNotifier()
        self.change_notifier.changed.connect(self._on_data_changed)

    def init_ui(self):
        self.setWindowTitle("Immersion Cell Manager")

        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create layout
        layout = QVBoxLayout()
        
        # Create tab widget
        self.tabs = QTabWidget()

        # Create station_summary_tab first so we can pass its callback to cells_mapping.
        # It gets the cells manager too, to reuse the cell editor for episodes.
        # on_cells_changed lets it refresh Cells Mapping when it frees a cell
        # (created below; the lambda is only called on later user interaction).
        self.station_summary_tab = StationSummary(
            self.summary_manager, self.cells_manager,
            on_cells_changed=lambda: self.cells_mapping_tab.reload_data(),
        )

        # Create cells_mapping_tab with a callback function to log channel usage
        def on_channel_logged(channel: str, row_data: dict):
            self.station_summary_tab.log_channel_usage(channel, row_data)

        def on_project_removed(project_name: str):
            # Archive/restore keeps the project on existing channels + history;
            # just refresh so it (dis)appears in the assignment dropdowns.
            self.cells_mapping_tab.reload_data()
            self.station_summary_tab.reload_data()

        def on_project_renamed(old_name: str, new_name: str):
            self.cells_manager.rename_project(old_name, new_name)
            self.summary_manager.rename_project_in_history(old_name, new_name)
            self.cells_mapping_tab.reload_data()
            self.station_summary_tab.reload_data()

        # Refresh the calibration tab when a channel is added/deleted, since its
        # channel list mirrors the cells (avoids re-querying on every tab switch).
        def on_channels_changed():
            self.calibration_tab.reload_data()

        self.cells_mapping_tab = CellsMapping(
            self.cells_manager,
            on_channel_logged=on_channel_logged,
            on_project_removed=on_project_removed,
            on_project_renamed=on_project_renamed,
            on_channels_changed=on_channels_changed,
            calibration_manager=self.calibration_manager,
        )

        # A calibration verdict couples to the cell status: a Reject frees the
        # cell into "In repair" (comment-only); an Approve returns an In-repair
        # cell to "Available" (it won't disturb an In-use cell).
        def on_calibration_decision(channel: str, passed: bool):
            if passed:
                cell = self.cells_manager.get_cell_by_channel(channel)
                if (cell.get("status") or "").strip().lower() == "in repair":
                    self.cells_manager.set_channel_status_cleared(channel, "Available")
            else:
                self.cells_manager.set_channel_status_cleared(
                    channel, "In repair",
                    comment="Set to In repair by a failed calibration.",
                )
            self.cells_mapping_tab.reload_data()
            self.station_summary_tab.reload_data()

        self.calibration_tab = CalibrationTab(
            self.calibration_manager, on_decision=on_calibration_decision
        )

        self.logbook_tab = LogbookTab(self.logbook_manager)

        self.tabs.addTab(self.cells_mapping_tab, "Cells mapping")
        self.tabs.addTab(self.station_summary_tab, "Station Summary")
        self.tabs.addTab(self.calibration_tab, "Channel Calibration")
        self.tabs.addTab(self.logbook_tab, "IC Logbook")


        # Apply tab styling
        self._apply_tab_styling()

        layout.addWidget(self.tabs)

        # Set layout
        central_widget.setLayout(layout)

    def _on_data_changed(self):
        """Handle data changes detected in the database (possibly another user)."""
        # Drop the cached project list so external project edits (colors,
        # renames, additions) are reflected on the next reload/repaint.
        invalidate_projects_cache()
        self.cells_mapping_tab.reload_data()
        self.station_summary_tab.reload_data()
        self.calibration_tab.reload_data()

    def _apply_tab_styling(self) -> None:
        """Apply modern styling to the tab widget."""
        tab_style = """
            QTabWidget::pane {
                border: 1px solid #E1E1E1;
            }
            QTabBar::tab {
                background-color: #F5F5F5;
                color: #1F1F1F;
                padding: 10px 24px;
                margin-right: 2px;
                font-weight: 500;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
                border: none;
            }
            QTabBar::tab:hover {
                background-color: #ECECEC;
            }
            QTabBar::tab:selected {
                background-color: #FFFFFF;
                color: #55BDBD;
                border-bottom: 3px solid #55BDBD;
                padding: 10px 24px;
            }
        """
        self.tabs.setStyleSheet(tab_style)

    def closeEvent(self, event):
        """Clean up resources when closing."""
        self.change_notifier.stop()
        super().closeEvent(event)


def run_app():
    """Initialize and run the PyQt6 application"""
    app = QApplication(sys.argv)
    try:
        window = MainWindow()
    except DatabaseError as e:
        QMessageBox.critical(None, "Database error", str(e))
        sys.exit(1)
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_app()

