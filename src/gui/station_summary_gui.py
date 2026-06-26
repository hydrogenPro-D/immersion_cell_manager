from datetime import timedelta, date

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor

from src.gui.styles.tab_styles import TAB_STYLE
from src.gui.widgets.gantt_chart_widget import GanttChartWidget
from src.gui.widgets.episode_info_dialog import EpisodeInfoDialog


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

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
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

        self.count_badge = QLabel("0 cells")
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

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(20, 50, 70, 35))
        toolbar.setGraphicsEffect(shadow)

        return toolbar

    # ----------------------------------------------------------- Rendering
    def _refresh(self) -> None:
        """Reload data from the manager and rebuild the chart + statistics."""
        self._all_rows = self.manager.get_channel_history()
        self._date_window = self._compute_date_window(
            self.manager.get_date_range()
        )

        self._render_filtered()
        self._build_stats()

        # Defer scroll positioning until after layout is complete.
        QTimer.singleShot(100, self._scroll_to_today)

    def _on_search_changed(self, _text: str) -> None:
        """Re-render the chart when the project-ID filter changes."""
        self._render_filtered()
        # Keep today in view after the chart rebuilds.
        QTimer.singleShot(0, self._scroll_to_today)

    def _render_filtered(self) -> None:
        """Push the (optionally project-filtered) rows into the chart."""
        if self._date_window is None:
            return

        rows = self._filter_rows(self.search_input.text())
        self.count_badge.setText(
            f"{len(rows)} cell{'s' if len(rows) != 1 else ''}"
        )

        min_date, max_date, floor_date = self._date_window
        self.gantt.set_data(rows, min_date, max_date, floor_date)

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
                filtered.append({"channel": row["channel"], "episodes": matching})
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
        """Open a read-only details window for a double-clicked bar."""
        dialog = EpisodeInfoDialog(episode, self)
        dialog.exec()

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
        """Reload data from the manager (called when external changes occur)."""
        self._refresh()

    def log_channel_usage(self, channel: str, row_data: dict) -> None:
        """Log a channel usage and refresh the view.

        Called from the cells_mapping tab when a channel is activated.
        ``row_data`` is the full row dict with all mapper columns.
        """
        self.manager.log_channel_usage(channel, row_data)
        self.reload_data()



