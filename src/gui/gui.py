import sys
from datetime import date, datetime, timedelta
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QTabWidget, QMessageBox,
    QTabBar,
)
from PyQt6.QtCore import Qt, QEventLoop, QEvent, QObject, QTimer
from src.data.db import DatabaseChangeNotifier, DatabaseError
from src.splash import EXTRA_BREATHS
from src.app_version import current_version, UNKNOWN
from src.data.immersion_cells_manager import ImmersionCellsManager
from src.data.station_summary_manager import StationSummaryManager
from src.data.calibration_manager import CalibrationManager
from src.data.logbook_manager import LogbookManager
from src.data.inventory_manager import InventoryManager
from src.data.event_log_manager import EventLogManager
from src.data.experiment_plan_manager import ExperimentPlanManager
from src.data.projects_manager import invalidate_projects_cache
from src.gui.cells_mapping import CellsMapping
from src.gui.station_summary_gui import StationSummary
from src.gui.calibration_gui import CalibrationTab
from src.gui.logbook_gui import LogbookTab, offer_logbook_entry
from src.gui.inventory_gui import InventoryTab
from src.gui.event_log_gui import EventLogTab
from src.gui.experiment_planning_gui import ExperimentPlanningTab


def load_managers() -> dict:
    """Connect and load every manager. They hold no Qt objects, so main.py runs
    this on a worker thread while the splash pulses."""
    inventory = InventoryManager()
    return {
        "cells": ImmersionCellsManager(),
        "summary": StationSummaryManager(),
        "calibration": CalibrationManager(),
        "logbook": LogbookManager(),
        "inventory": inventory,
        "events": EventLogManager(inventory),
        "plans": ExperimentPlanManager(),
    }


# Which tab shows which icm tables (for the 5-second change check).
_LEGACY_TABLES = {"cells", "channel_history", "projects", "channel_calibration"}
_INVENTORY_TABLES = {"inventory_item", "inventory_config"}
_EVENT_TABLES = {"event_type", "event_type_cost", "event_log", "event_log_cost"}


class _TabBarWheelBlocker(QObject):
    """Stops the mouse wheel from switching tabs (installed on each tab bar)."""

    def eventFilter(self, obj, event):
        return event.type() == QEvent.Type.Wheel and isinstance(obj, QTabBar)


class MainWindow(QMainWindow):
    def __init__(self, managers: dict = None, pump=None):
        """``managers`` comes from :func:`load_managers` (loaded here if omitted);
        ``pump`` is called between tab builds so the splash can repaint."""
        super().__init__()
        # Create the managers once at the application level
        m = managers or load_managers()
        self.cells_manager = m["cells"]
        self.summary_manager = m["summary"]
        self.calibration_manager = m["calibration"]
        self.logbook_manager = m["logbook"]
        self.inventory_manager = m["inventory"]
        self.event_manager = m["events"]
        self.plan_manager = m["plans"]
        self._pump = pump or (lambda: None)
        self._wheel_blocker = _TabBarWheelBlocker(self)
        self.init_ui()
        self._block_tab_wheel(self)

        # Poll the database for external changes (other users) and refresh.
        self._pending_tables = set()  # changes held while a dialog is open
        self.change_notifier = DatabaseChangeNotifier()
        self.change_notifier.changed.connect(self._on_data_changed)

    def _block_tab_wheel(self, root: QWidget) -> None:
        # Per tab bar: an app-wide filter would run Python for every event.
        for bar in root.findChildren(QTabBar):
            bar.installEventFilter(self._wheel_blocker)

    def init_ui(self):
        # "(dev build)" tells a bug screenshot from source apart from a release.
        version = current_version()
        self.setWindowTitle(f"Immersion Cell Manager  v{version}" if version != UNKNOWN
                            else "Immersion Cell Manager  (dev build)")

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
            on_experiment_finished=self._offer_logbook_entry,
        )
        self._pump()

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
            on_experiment_finished=self._offer_logbook_entry,
        )
        self._pump()

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
        self._pump()

        # The logbook is the slowest tab to build, so it's built on first open.
        self.logbook_tab = None

        self.inventory_tab = InventoryTab(
            self.inventory_manager,
            on_items_changed=lambda: self.event_log_tab.reload())
        # The event manager has re-read the inventory already: just redraw.
        self.event_log_tab = EventLogTab(
            self.event_manager, on_inventory_changed=self.inventory_tab.refresh)
        self.planning_tab = ExperimentPlanningTab(
            self.plan_manager, self.cells_manager,
            protocols=lambda: self.logbook_manager.get_recent_values("protocol"),
            on_load=self._load_plan)

        self.tabs.addTab(self.cells_mapping_tab, "Cells mapping")
        self.tabs.addTab(self.station_summary_tab, "Station Summary")
        self.tabs.addTab(self.calibration_tab, "Channel Calibration")
        self._logbook_index = self.tabs.addTab(QWidget(), "IC Logbook")
        self.tabs.addTab(self.inventory_tab, "Inventory")
        self.tabs.addTab(self.event_log_tab, "Event Log")
        self.tabs.addTab(self.planning_tab, "Experiment planning")
        self.tabs.currentChanged.connect(self._build_logbook_on_first_open)


        # Apply tab styling
        self._apply_tab_styling()

        layout.addWidget(self.tabs)

        # Set layout
        central_widget.setLayout(layout)

    def _offer_logbook_entry(self, cell: dict, undo=None) -> None:
        """A cell left In use: offer its experiment to the IC Logbook, prefilled
        from the cell (the rest is asked in the form). ``undo`` puts the cell
        back to In use; it backs the form's "Go back" button."""
        prefill = {
            "ic_id": cell.get("data_filename", ""),
            "owner": cell.get("current_owner", ""),
            "assembled_by": cell.get("assembled_by", ""),
            "test_length_h": self.cells_manager.duration_hours(cell),
            "experiment_finished_on": date.today().isoformat(),
        }
        outcome, category = offer_logbook_entry(
            self, self.logbook_manager, prefill, cell.get("channel", ""),
            can_go_back=undo is not None)
        if outcome == "back":
            undo()
        elif outcome == "added" and self.logbook_tab is not None:
            self.logbook_tab.show_added(category)

    def _load_plan(self, plan: dict, channel: str) -> bool:
        """Open ``channel``'s Cells mapping editor prefilled from ``plan``; the
        user completes it. True once the cell was saved In use."""
        now = datetime.now()
        prefill = {
            "Status": "In use",
            "Project ID": plan.get("project_id", ""),
            "Anode": plan.get("anode", ""),
            "Cathode": plan.get("cathode", ""),
            "Current owner": plan.get("name", ""),  # the plan's Name is its requester
            "Start date": now.strftime("%Y-%m-%d %H:00"),
        }
        try:
            hours = float((plan.get("test_length_h") or "").replace(",", "."))
            prefill["Expected end date"] = (now + timedelta(hours=hours)).strftime("%Y-%m-%d")
        except ValueError:
            pass
        notes = [f"{label}: {plan[key]}" for key, label in (("protocol", "Protocol"),
                                                             ("aim", "Aim")) if plan.get(key)]
        if notes:
            prefill["Comments"] = "\n".join(notes)
        self.tabs.setCurrentWidget(self.cells_mapping_tab)
        loaded = self.cells_mapping_tab.open_plan(channel, prefill)
        if not loaded:
            self.tabs.setCurrentWidget(self.planning_tab)  # cancelled: back to the plan
        return loaded

    def _build_logbook_on_first_open(self, index: int) -> None:
        if index != self._logbook_index or self.logbook_tab is not None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.logbook_tab = LogbookTab(self.logbook_manager)
            placeholder = self.tabs.widget(index)
            self.tabs.blockSignals(True)  # the swap below would re-enter this slot
            self.tabs.removeTab(index)
            self.tabs.insertTab(index, self.logbook_tab, "IC Logbook")
            self.tabs.setCurrentIndex(index)
            self.tabs.blockSignals(False)
            placeholder.deleteLater()
            self._block_tab_wheel(self.logbook_tab)
        finally:
            QApplication.restoreOverrideCursor()

    def _on_data_changed(self, tables: set):
        """Refresh the tabs that show ``tables`` (changed in the database,
        usually by another user)."""
        self._pending_tables |= tables
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget():
            # Rebuilding under an open dialog would pull rows from under it.
            QTimer.singleShot(1000, lambda: self._on_data_changed(set()))
            return
        tables, self._pending_tables = self._pending_tables, set()
        if not tables:
            return
        if tables & _LEGACY_TABLES:
            # Drop the cached project list so external project edits (colors,
            # renames, additions) are reflected on the next reload/repaint.
            invalidate_projects_cache()
            self.cells_mapping_tab.reload_data()
            self.station_summary_tab.reload_data()
            self.calibration_tab.reload_data()
            self.planning_tab.refresh()  # the busy-cell warnings follow the cells
        if tables & _INVENTORY_TABLES:
            self.inventory_tab.reload()  # first: event dialogs read stock from it
        if tables & _EVENT_TABLES:
            self.event_log_tab.reload()
        if "experiment_plan" in tables:
            self.planning_tab.reload()
        if any(t.startswith("ic_logbook") for t in tables):
            if self.logbook_tab is not None:
                self.logbook_tab.reload_data()
            else:
                self.logbook_manager.reload()  # read when the tab is first opened

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


def run_app(app=None, splash=None, managers=None, load_error=None):
    """Build the main window and run the event loop.

    main.py passes its QApplication, the startup splash, and the managers it
    loaded in the background (or the error that loading raised). All optional,
    so this module still runs on its own.
    """
    app = app or QApplication(sys.argv)
    # Let the splash repaint between tab builds; user input waits until the
    # window is shown.
    pump = None
    if splash is not None:
        pump = lambda: app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    try:
        if load_error is not None:
            raise load_error
        window = MainWindow(managers, pump=pump)
    except DatabaseError as e:
        if splash is not None:
            splash.close_now()  # don't let it sit over the error dialog
        QMessageBox.critical(None, "Database error", str(e))
        sys.exit(1)
    if splash is not None:
        # Open on the splash's screen, so both pick the same monitor.
        screen = splash.screen()
        if screen is not None:
            window.setGeometry(screen.availableGeometry())
        # Shown but invisible until the splash's extra breath ends: the costly
        # first show happens now, so the breath and the fade stay smooth.
        window.setWindowOpacity(0.0)
    window.showMaximized()
    if splash is not None:
        splash.finish(window, extra_breaths=EXTRA_BREATHS)
    sys.exit(app.exec())


if __name__ == "__main__":
    run_app()

