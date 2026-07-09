import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QTabWidget, QMessageBox,
)
from PyQt6.QtCore import Qt
from src.data.db import DatabaseChangeNotifier, DatabaseError
from src.data.immersion_cells_manager import ImmersionCellsManager
from src.data.station_summary_manager import StationSummaryManager
from src.data.projects_manager import invalidate_projects_cache
from src.gui.cells_mapping import CellsMapping
from src.gui.station_summary_gui import StationSummary


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Create the managers once at the application level
        self.cells_manager = ImmersionCellsManager()
        self.summary_manager = StationSummaryManager()
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
        self.station_summary_tab = StationSummary(
            self.summary_manager, self.cells_manager
        )

        # Create cells_mapping_tab with a callback function to log channel usage
        def on_channel_logged(channel: str, row_data: dict):
            self.station_summary_tab.log_channel_usage(channel, row_data)

        def on_project_removed(project_name: str):
            self.cells_manager.clear_project(project_name)
            self.summary_manager.remove_project_from_history(project_name)
            self.cells_mapping_tab.reload_data()
            self.station_summary_tab.reload_data()

        def on_project_renamed(old_name: str, new_name: str):
            self.cells_manager.rename_project(old_name, new_name)
            self.summary_manager.rename_project_in_history(old_name, new_name)
            self.cells_mapping_tab.reload_data()
            self.station_summary_tab.reload_data()

        self.cells_mapping_tab = CellsMapping(
            self.cells_manager,
            on_channel_logged=on_channel_logged,
            on_project_removed=on_project_removed,
            on_project_renamed=on_project_renamed,
        )
        self.tabs.addTab(self.cells_mapping_tab, "Cells mapping")
        self.tabs.addTab(self.station_summary_tab, "Station Summary")


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

