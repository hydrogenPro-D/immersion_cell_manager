import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QTabWidget
from PyQt6.QtCore import Qt
from src.gui.immersion_cells import ImmersionCellsTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Immersion Cell Manager")

        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create layout
        layout = QVBoxLayout()
        
        # Create tab widget
        self.tabs = QTabWidget()

        # Create and add tabs
        self.immersion_cells_tab = ImmersionCellsTab()
        self.tabs.addTab(self.immersion_cells_tab, "Immersion Cells")

        # Apply tab styling
        self._apply_tab_styling()

        layout.addWidget(self.tabs)

        # Set layout
        central_widget.setLayout(layout)

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


def run_app():
    """Initialize and run the PyQt6 application"""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_app()

