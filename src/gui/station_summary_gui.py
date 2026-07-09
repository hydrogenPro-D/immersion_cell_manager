from datetime import timedelta, date

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QGraphicsDropShadowEffect,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor

from src.data.enums import CellStatus
from src.gui.styles.tab_styles import TAB_STYLE
from src.gui.widgets.gantt_chart_widget import GanttChartWidget
from src.gui.widgets.episode_info_dialog import EpisodeInfoDialog
from src.gui.widgets.edit_row_dialog import EditRowDialog
from src.gui.widgets.changes_dialog import ChangesDialog
from src.gui.widgets.zoom_control import ZoomControl


class StationSummary(QWidget):
    """Gantt-style history view: one row per channel, bars over a day axis."""

    # How far past today the timeline extends (2 weeks of headroom).
    FUTURE_DAYS = 14

    # How many days of history to load initially. Older episodes still exist
    # and are loaded lazily by the chart as the user scrolls left.
    INITIAL_PAST_DAYS = 90

    # Where "today" should appear horizontally (fraction of the viewport width
    # from the left edge). 0.5 = center, >0.5 = right of center.
    TODAY_VIEW_FRACTION = 0.75

    def __init__(self, manager, cells_manager=None):
        super().__init__()
        self.manager = manager
        # Cells manager: lets us reuse the cell editor (EditRowDialog) to modify
        # an episode, writing to the history instead of the cells table.
        self.cells_manager = cells_manager
        self._initial_scroll_done = False
        # Cache of the unfiltered data + computed axis, so typing in the search
        # box re-filters without re-reading from disk.
        self._all_rows = []
        self._date_window = None
        self.init_ui()
        self._refresh()

    def showEvent(self, event):
        """Position the scroll once the tab is first shown (real width known)."""
        super().showEvent(event)
        if not self._initial_scroll_done:
            self._initial_scroll_done = True
            QTimer.singleShot(0, self._scroll_to_today)

    # ----------------------------------------------------------------- UI
    def init_ui(self):
        """Initialize the Station Summary tab UI"""
        self.setObjectName("TabRoot")
        self.setStyleSheet(TAB_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(16)

        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())

        # Gantt chart with sticky row + column headers.
        self.gantt = GanttChartWidget()
        self.gantt.episode_activated.connect(self._on_episode_activated)
        root.addWidget(self.gantt, 1)

        # Statistics footer
        self.stats_frame = QFrame()
        self.stats_frame.setObjectName("Toolbar")
        self.stats_layout = QHBoxLayout(self.stats_frame)
        self.stats_layout.setContentsMargins(14, 10, 14, 10)
        self.stats_layout.setSpacing(10)
        root.addWidget(self.stats_frame)

    # ------------------------------------------------------------ Header
    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("PageHeader")
        header.setFixedHeight(70)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        title = QLabel("Station Summary")
        title.setObjectName("PageTitle")
        layout.addWidget(title, 1)

        self.count_badge = QLabel("0 operational cells")
        self.count_badge.setObjectName("PageBadge")
        self.count_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.count_badge, 0, Qt.AlignmentFlag.AlignVCenter)

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
        self.search_input.setPlaceholderText("Filter by project ID…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)

        layout.addWidget(search_label)
        layout.addWidget(self.search_input, 1)

        layout.addWidget(ZoomControl(lambda d: self.gantt.zoom_step(d)))

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(20, 50, 70, 35))
        toolbar.setGraphicsEffect(shadow)

        return toolbar

    # ----------------------------------------------------------- Rendering
    def _refresh(self, preserve_view: bool = False) -> None:
        """Reload data from the manager and rebuild the chart + statistics.

        With ``preserve_view`` the current scroll position is kept (used after
        edits / external changes so the view doesn't jump back to today).
        """
        self._all_rows = self.manager.get_channel_history()
        self._date_window = self._compute_date_window(
            self.manager.get_date_range()
        )

        self._render_filtered(preserve_view=preserve_view)
        self._build_stats()

        if not preserve_view:
            # Defer scroll positioning until after layout is complete.
            QTimer.singleShot(100, self._scroll_to_today)

    def _on_search_changed(self, _text: str) -> None:
        """Re-render the chart when the project-ID filter changes.

        Preserve the current scroll position — filtering shouldn't jump the view.
        """
        self._render_filtered(preserve_view=True)

    def _render_filtered(self, preserve_view: bool = False) -> None:
        """Push the (optionally project-filtered) rows into the chart."""
        if self._date_window is None:
            return

        rows = self._filter_rows(self.search_input.text())
        # Match the Cells Mapping badge: count operational cells (everything
        # except In repair), not the raw total.
        operational = sum(
            1 for r in rows
            if (r.get("status") or "").strip().lower() != "in repair"
        )
        self.count_badge.setText(
            f"{operational} operational cell{'s' if operational != 1 else ''}"
        )

        min_date, max_date, floor_date = self._date_window
        self.gantt.set_data(
            rows, min_date, max_date, floor_date, preserve_view=preserve_view
        )

    def _filter_rows(self, text: str) -> list:
        """Filter rows by project ID.

        Returns only channels that ran a project whose ID contains ``text``
        (case-insensitive), and on those channels keeps only the matching
        episodes. An empty search returns every channel unchanged.
        """
        needle = (text or "").strip().lower()
        if not needle:
            return self._all_rows

        filtered = []
        for row in self._all_rows:
            matching = [
                ep for ep in row["episodes"]
                if needle in (ep.get("project") or "").lower()
            ]
            if matching:
                filtered.append({
                    "channel": row["channel"],
                    "status": row.get("status", ""),
                    "episodes": matching,
                })
        return filtered

    def _build_stats(self) -> None:
        """Populate the statistics footer."""
        self._clear_layout(self.stats_layout)

        stats = self.manager.get_statistics()

        title = QLabel("Statistics:")
        title.setObjectName("StatusLabel")
        self.stats_layout.addWidget(title)

        self.stats_layout.addWidget(
            self._make_stat_chip("Nr of channels", stats["total"])
        )

        for status, count in stats["status_counts"].items():
            self.stats_layout.addWidget(self._make_stat_chip(status, count))

        self.stats_layout.addStretch(1)

    def _make_stat_chip(self, label: str, value) -> QLabel:
        chip = QLabel(f"{label}: {value}")
        chip.setObjectName("PageBadge")
        return chip

    # ------------------------------------------------------- Interactions
    def _on_episode_activated(self, episode: dict) -> None:
        """Open a details window for a double-clicked bar; delete/modify on request."""
        dialog = EpisodeInfoDialog(episode, self)
        dialog.exec()
        if dialog.delete_requested:
            self._delete_episode(episode)
        elif dialog.modify_requested:
            self._modify_episode(episode)

    def _modify_episode(self, episode: dict) -> None:
        """Open the cell editor on this episode; save to the history, not the cell."""
        episode_id = (episode.get("data") or {}).get("id")
        if not episode_id or self.cells_manager is None:
            QMessageBox.warning(
                self, "Could not modify",
                "Couldn't determine which entry to edit.",
            )
            return
        table = self._episode_as_table(episode)
        # Episodes are experiments: hide cell-only states (Available / In repair).
        dialog = EditRowDialog(
            table, 0, self.cells_manager, self, is_add_mode=False,
            status_choices=CellStatus.experiment_values(),
        )
        saved = []
        dialog.row_saved.connect(saved.append)
        dialog.exec()
        # Persist + refresh only after the editor has fully closed, so the chart
        # rebuild runs in the normal event loop (not the dialog's modal loop),
        # where the viewport geometry is settled and the overlays land correctly.
        if saved:
            self._save_episode_edit(episode_id, episode, saved[-1])

    def _episode_as_table(self, episode: dict) -> QTableWidget:
        """1-row table of the episode's values, in the cell editor's columns."""
        cols = self.cells_manager.get_column_names()
        mapping = self.cells_manager.COLUMNS_MAPPING
        data = episode.get("data", {})
        table = QTableWidget(1, len(cols))
        for i, display in enumerate(cols):
            key = mapping.get(display, "")
            value = "" if key == "duration" else str(data.get(key, "") or "")
            table.setItem(0, i, QTableWidgetItem(value))
        return table

    def _save_episode_edit(self, episode_id, episode: dict, row_data: list) -> None:
        """Map the edited cell columns back to history fields and persist."""
        cols = self.cells_manager.get_column_names()
        mapping = self.cells_manager.COLUMNS_MAPPING
        values = {}
        for i, display in enumerate(cols):
            key = mapping.get(display)
            if not key or key == "duration":
                continue
            values[key] = row_data[i] if i < len(row_data) else ""
        # Fields absent from the cell columns: keep the episode's own values.
        # (row_data has the original filename appended in edit mode.)
        data = episode.get("data", {})
        values["end_date"] = str(data.get("end_date", "") or "")
        # Transitioning into "Test finished" stamps the end at today (an ongoing
        # bar was only extended to today at render time, so its stored end can be
        # earlier). Re-saving an already-finished test keeps its stored end.
        old_status = (data.get("status") or "").strip().lower()
        if (values.get("status") or "").strip().lower() == "test finished" \
                and old_status != "test finished":
            values["end_date"] = date.today().strftime("%Y-%m-%d")
        original = row_data[len(cols)] if len(row_data) > len(cols) else ""
        values["original_data_filename"] = (
            original or str(data.get("original_data_filename", "") or "")
        )
        channel = (values.get("channel") or "").strip()
        print(f"[MODIFY] updating episode id={episode_id} channel={channel!r} "
              f"values={values}")
        changes = self._episode_changes(data, values)
        if self.manager.update_episode(episode_id, values):
            print(f"[MODIFY] episode id={episode_id} updated OK")
            self._sync_live_cell(channel, data, row_data[:len(cols)])
            self.reload_data()
            self._show_changes_dialog(channel, changes)
        else:
            print(f"[MODIFY] episode id={episode_id} update FAILED")
            QMessageBox.warning(
                self, "Update failed",
                "The experiment could not be updated. Please try again.",
            )

    def _sync_live_cell(self, channel: str, data: dict, cell_row: list) -> None:
        """Mirror the edit onto the channel's cell when this is its live episode.

        Only the latest experiment per channel lives in ``icm.cells``, matched by
        data_filename. Past episodes and cleared cells (blank/other filename)
        don't match, so they're left untouched. No filename → can't identify the
        live cell → no sync.
        """
        episode_filename = str(data.get("data_filename") or "").strip()
        if not episode_filename:
            return
        cell = self.cells_manager.get_cell_by_channel(channel)
        if (cell.get("data_filename") or "").strip() != episode_filename:
            return  # not this channel's current experiment
        try:
            self.cells_manager.update_row_by_channel(cell_row)
            print(f"[MODIFY] synced live cell for channel={channel!r}")
        except Exception as e:  # best-effort: history is already updated
            print(f"[MODIFY] cell sync FAILED for channel={channel!r}: {e}")

    # Fields compared for the post-save "what changed" summary (Channel is
    # read-only; id / original_data_filename are internal).
    _CHANGE_LABELS = [
        ("project_id", "Project ID"),
        ("current_owner", "Current owner"),
        ("assembled_by", "Assembled by"),
        ("status", "Status"),
        ("start_date", "Start date"),
        ("start_hour", "Start hour"),
        ("end_date", "End date"),
        ("expected_end_date", "Expected end date"),
        ("cathode", "Cathode"),
        ("anode", "Anode"),
        ("separator", "Separator"),
        ("added_water_b", "Added water by timing"),
        ("data_filename", "Data filename"),
        ("comments", "Comments"),
    ]

    def _episode_changes(self, old_data: dict, new_values: dict) -> list:
        """Return ``[(label, old, new), ...]`` for fields whose value changed."""
        changes = []
        for key, label in self._CHANGE_LABELS:
            old = str(old_data.get(key, "") or "").strip()
            new = str(new_values.get(key, "") or "").strip()
            if old != new:
                changes.append((label, old, new))
        return changes

    def _show_changes_dialog(self, channel: str, changes: list) -> None:
        """Show an OK-only styled summary of what was changed (Station Summary only)."""
        ChangesDialog(channel, changes, self).exec()

    def _delete_episode(self, episode: dict) -> None:
        """Delete the episode's history row (confirmed in the dialog) + refresh."""
        data = episode.get("data") or {}
        episode_id = data.get("id")
        if not episode_id:
            QMessageBox.warning(
                self, "Could not delete",
                "Couldn't determine which entry to delete.",
            )
            return
        channel = (data.get("channel") or "").strip()
        filename = (data.get("data_filename") or "").strip()
        print(f"[DELETE] deleting episode id={episode_id} channel={channel!r} "
              f"filename={filename!r} status={(data.get('status') or '').strip()!r}")
        if self.manager.delete_episode(episode_id):
            print(f"[DELETE] episode id={episode_id} deleted OK")
            self.reload_data()
        else:
            print(f"[DELETE] episode id={episode_id} delete FAILED")
            QMessageBox.warning(
                self, "Delete failed",
                "The entry could not be deleted. Please try again.",
            )

    # -------------------------------------------------------------- Helpers
    def _scroll_to_today(self) -> None:
        self.gantt.scroll_to_date(date.today(), self.TODAY_VIEW_FRACTION)

    def _compute_date_window(self, data_range):
        """Decide the chart's date axis.

        Returns ``(min_date, max_date, floor_date)`` where:

        * ``min_date`` – left edge initially loaded (today − ``INITIAL_PAST_DAYS``).
        * ``max_date`` – right edge (today + ``FUTURE_DAYS``, never clipping data
          that extends further into the future).
        * ``floor_date`` – the oldest date the chart may lazily scroll back to.
          This is the earliest episode (so "all history and nothing more"); if
          the data is younger than the initial window there is nothing older to
          load, so the floor is just the initial left edge.
        """
        today = date.today()
        max_future = today + timedelta(days=self.FUTURE_DAYS)
        initial_min = today - timedelta(days=self.INITIAL_PAST_DAYS)

        if data_range is None:
            return initial_min, max_future, initial_min

        data_min, data_max = data_range
        max_date = max(max_future, data_max)
        floor_date = min(data_min, initial_min)
        return initial_min, max_date, floor_date

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    # ----------------------------------------------------------- Data ops
    def reload_data(self) -> None:
        """Reload data (after edits / external changes); keeps the current view."""
        self._refresh(preserve_view=True)

    def log_channel_usage(self, channel: str, row_data: dict) -> None:
        """Log a channel usage and refresh the view.

        Called from the cells_mapping tab when a channel is activated.
        ``row_data`` is the full row dict with all mapper columns.
        """
        self.manager.log_channel_usage(channel, row_data)
        self.reload_data()



