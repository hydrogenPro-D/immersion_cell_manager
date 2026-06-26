"""A Gantt-style chart widget with sticky row and column headers.

Implemented as **two synchronized tables** side by side:

* ``channel_table`` – a single-column table holding the channel names. Its
  built-in horizontal header ("Channel") stays frozen at the top and the column
  itself is frozen on the left (it is simply a separate widget).
* ``timeline_table`` – the day/episode grid. Its built-in horizontal header
  (week + day labels) is frozen at the top by Qt automatically.

The two tables share the same rows and row height; their vertical scrollbars
are kept in sync so the channel names always line up with their timeline rows.
The timeline table owns the visible scrollbars.
"""

from datetime import timedelta, date

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QLabel,
    QStyle,
    QProxyStyle,
)
from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QRect
from PyQt6.QtGui import QColor, QPainter, QPen, QLinearGradient

from src.data.enums import CellStatus

# Shared accent palette for the "today" highlight.
TODAY_ACCENT = "#3FA3A3"
TODAY_ACCENT_DARK = "#2C8585"


class _FastTooltipStyle(QProxyStyle):
    """Proxy style that shows tooltips almost immediately on hover."""

    # Delay (ms) before a tooltip appears. Default Qt value is ~700 ms.
    WAKE_UP_DELAY = 120

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return self.WAKE_UP_DELAY
        return super().styleHint(hint, option, widget, returnData)


class _TodayHeaderView(QHeaderView):
    """Horizontal header that paints the 'today' column with a teal accent."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._today_col = -1

    def set_today_col(self, col: int) -> None:
        if col != self._today_col:
            self._today_col = col
            self.viewport().update()

    def paintSection(self, painter, rect, logicalIndex) -> None:
        if logicalIndex != self._today_col:
            super().paintSection(painter, rect, logicalIndex)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Solid accent gradient fill so the header cell clearly reads as "today".
        gradient = QLinearGradient(
            float(rect.left()), float(rect.top()),
            float(rect.left()), float(rect.bottom()),
        )
        gradient.setColorAt(0.0, QColor(TODAY_ACCENT))
        gradient.setColorAt(1.0, QColor(TODAY_ACCENT_DARK))
        painter.fillRect(rect, gradient)

        # Same two-line (week / day) label the other sections show, in white.
        model = self.model()
        text = ""
        if model is not None:
            value = model.headerData(
                logicalIndex,
                Qt.Orientation.Horizontal,
                Qt.ItemDataRole.DisplayRole,
            )
            text = "" if value is None else str(value)

        font = painter.font()
        font.setBold(True)
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(
            rect.adjusted(0, 5, 0, 0),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            text,
        )
        painter.restore()


class _TodayColumnOverlay(QWidget):
    """Transparent overlay drawing a vertical 'today' band over the grid.

    Lives on top of the timeline viewport but is transparent to mouse events,
    so bar hover/tooltips keep working underneath it.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._x = None  # viewport x of the column's left edge (None = hidden)
        self._w = 0

    def set_column(self, x, width: int) -> None:
        self._x = x
        self._w = width
        self.update()

    def paintEvent(self, event) -> None:
        if self._x is None or self._w <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        height = self.height()
        band = QRect(int(self._x), 0, int(self._w), height)

        # Translucent fill: clearly highlights the column while keeping any
        # bars and row stripes underneath readable.
        fill = QColor(TODAY_ACCENT)
        fill.setAlpha(34)
        painter.fillRect(band, fill)

        # Crisp accent lines down both edges of the column.
        edge = QColor(TODAY_ACCENT)
        edge.setAlpha(210)
        pen = QPen(edge)
        pen.setWidth(2)
        painter.setPen(pen)
        left = int(self._x)
        right = int(self._x + self._w)
        painter.drawLine(left, 0, left, height)
        painter.drawLine(right, 0, right, height)


class GanttChartWidget(QWidget):
    """Reusable Gantt chart with sticky row + column headers."""

    # Emitted with the episode dict when a bar is double-clicked.
    episode_activated = pyqtSignal(dict)

    # How much to darken a bar's color while hovered (0..1, lower = darker).
    HOVER_DARKEN = 0.82

    # Layout metrics (pixels)
    DAY_WIDTH = 45
    ROW_HEIGHT = 30
    HEADER_HEIGHT = 48           # tall enough for the two-line week/day header
    CHANNEL_COL_WIDTH = 80

    # How many older days to load each time the user scrolls to the left edge.
    PAST_LOAD_DAYS = 90
    # Distance (in day columns) from the left edge that triggers a past load.
    PAST_LOAD_TRIGGER_DAYS = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._min_date = None
        self._max_date = None
        self._today_col = None
        self._today_overlay = None
        # Lazy "load more history on scroll-left" state.
        self._rows = []
        self._loaded_min = None   # left edge currently rendered
        self._floor = None        # oldest date we may scroll back to
        self._extending = False   # re-entrancy guard while rebuilding
        self._syncing = False
        self._selecting = False
        # Maps (row, start_col) -> {"label", "bg", "fg", "span"} for hover.
        self._bars = {}
        self._hovered_key = None
        # Shared style that makes tooltips pop up quickly (kept as an attribute
        # so it isn't garbage-collected while widgets reference it).
        self._fast_tooltip_style = _FastTooltipStyle()
        self._init_ui()

    # ----------------------------------------------------------------- UI
    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Left: channel names (sticky column) ---
        self.channel_table = QTableWidget(0, 1)
        self.channel_table.setHorizontalHeaderLabels(["Channel"])
        self.channel_table.setFixedWidth(self.CHANNEL_COL_WIDTH)
        self._configure_common(self.channel_table)
        self.channel_table.setColumnWidth(0, self.CHANNEL_COL_WIDTH)
        self.channel_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        # Hide the channel table's own scrollbars; it follows the timeline.
        self.channel_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.channel_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        # Wrap the channel table so we can reserve space at the bottom equal to
        # the timeline's horizontal scrollbar height, keeping the last rows of
        # both tables aligned.
        scrollbar_extent = self.style().pixelMetric(
            QStyle.PixelMetric.PM_ScrollBarExtent
        )
        left_container = QWidget()
        left_container.setFixedWidth(self.CHANNEL_COL_WIDTH)
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 2*scrollbar_extent)
        left_layout.setSpacing(0)
        left_layout.addWidget(self.channel_table)
        layout.addWidget(left_container)

        # --- Right: timeline grid (sticky header, scrolls both ways) ---
        self.timeline_table = QTableWidget(0, 0)
        # Custom header so the "today" column can be painted with an accent.
        self._timeline_header = _TodayHeaderView(
            Qt.Orientation.Horizontal, self.timeline_table
        )
        self.timeline_table.setHorizontalHeader(self._timeline_header)
        self._configure_common(self.timeline_table)
        layout.addWidget(self.timeline_table, 1)

        # Overlay that paints the vertical "today" band over the grid.
        self._today_overlay = _TodayColumnOverlay(self.timeline_table.viewport())
        self._today_overlay.setGeometry(self.timeline_table.viewport().rect())
        self._today_overlay.show()
        # Keep the band aligned while scrolling horizontally, and lazily load
        # older history when the user reaches the left edge.
        self.timeline_table.horizontalScrollBar().valueChanged.connect(
            self._on_horizontal_scroll
        )

        # Keep both header rows the same height so row 0 lines up.
        self.channel_table.horizontalHeader().setFixedHeight(self.HEADER_HEIGHT)
        self.timeline_table.horizontalHeader().setFixedHeight(self.HEADER_HEIGHT)

        # Sync vertical scrolling between the two tables.
        self.timeline_table.verticalScrollBar().valueChanged.connect(
            self._sync_channel_scroll
        )
        self.channel_table.verticalScrollBar().valueChanged.connect(
            self._sync_timeline_scroll
        )
        # Vertical scrolling moves the viewport's children (including the today
        # overlay) along with the content, so snap the overlay back to span the
        # full viewport — otherwise the "today" band drifts off the top and the
        # highlight stops partway down.
        self.timeline_table.verticalScrollBar().valueChanged.connect(
            self._on_vertical_scroll
        )

        # Sync row selection so clicking either table highlights the whole row.
        self.timeline_table.itemSelectionChanged.connect(
            self._sync_selection_from_timeline
        )
        self.channel_table.itemSelectionChanged.connect(
            self._sync_selection_from_channel
        )

        # Double-clicking a bar opens its read-only details.
        self.timeline_table.cellDoubleClicked.connect(
            self._on_timeline_double_clicked
        )

        # Track the mouse so we can highlight the bar under the cursor.
        self.timeline_table.setMouseTracking(True)
        self.timeline_table.cellEntered.connect(self._on_cell_entered)
        self.timeline_table.viewport().installEventFilter(self)

        # Make tooltips (e.g. the full date on each day header) appear quickly.
        self.timeline_table.setStyle(self._fast_tooltip_style)
        self.timeline_table.horizontalHeader().setStyle(
            self._fast_tooltip_style
        )

    def _configure_common(self, table: QTableWidget) -> None:
        """Shared appearance/behaviour for both tables."""
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(self.ROW_HEIGHT)
        table.setShowGrid(False)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        table.setFrameShape(QTableWidget.Shape.NoFrame)
        # Alternating row colours, matching the Cells Mapping tab, plus a
        # subtle highlight for the selected row.
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            "QTableWidget {"
            " background-color: #FFFFFF;"
            " alternate-background-color: #F7FAFC;"
            " border: none; }"
            " QTableWidget::item:hover {"
            " background-color: transparent; }"
            " QTableWidget::item:selected {"
            " background-color: #D6ECEC; color: #0B3B3B; }"
        )
        table.horizontalHeader().setHighlightSections(False)
        table.horizontalHeader().setStyleSheet(
            "QHeaderView::section {"
            " background: #E2EAEF; color: #4A5A66; font-size: 11px;"
            " font-weight: 600; border: 1px solid #FFFFFF;"
            " padding-left: 4px; padding-top: 5px; }"
        )

    # -------------------------------------------------------- Scroll sync
    def _sync_channel_scroll(self, value: int) -> None:
        # Guard against the feedback loop. Don't use blockSignals here: the
        # table relies on the scrollbar's valueChanged signal to actually move
        # its viewport, so blocking it would freeze the content.
        if self._syncing:
            return
        self._syncing = True
        self.channel_table.verticalScrollBar().setValue(value)
        self._syncing = False

    def _sync_timeline_scroll(self, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.timeline_table.verticalScrollBar().setValue(value)
        self._syncing = False

    # ----------------------------------------------------- Selection sync
    def _sync_selection_from_timeline(self) -> None:
        self._mirror_selection(self.timeline_table, self.channel_table)

    def _sync_selection_from_channel(self) -> None:
        self._mirror_selection(self.channel_table, self.timeline_table)

    def _mirror_selection(self, source, target) -> None:
        if self._selecting:
            return
        self._selecting = True
        rows = source.selectionModel().selectedRows()
        if rows:
            target.selectRow(rows[0].row())
        else:
            target.clearSelection()
        self._selecting = False

    # ------------------------------------------------------ Bar activation
    def _on_timeline_double_clicked(self, row: int, column: int) -> None:
        """Emit ``episode_activated`` when a bar is double-clicked."""
        episode = self._episode_at(row, column)
        if episode:
            self.episode_activated.emit(episode)

    def _episode_at(self, row: int, column: int):
        """Return the episode covering ``(row, column)``, or ``None``.

        A bar occupies its start cell plus any spanned cells; spanned cells
        have no item of their own, so scan the row for the start cell whose
        span covers the clicked column.
        """
        item = self.timeline_table.item(row, column)
        if item is not None:
            episode = item.data(Qt.ItemDataRole.UserRole)
            if episode:
                return episode

        for col in range(column, -1, -1):
            start_item = self.timeline_table.item(row, col)
            if start_item is None:
                continue
            episode = start_item.data(Qt.ItemDataRole.UserRole)
            if not episode:
                continue
            span = start_item.data(Qt.ItemDataRole.UserRole + 1) or 1
            if col + span > column:
                return episode
            break
        return None

    # ----------------------------------------------------------- Bar hover
    def _on_cell_entered(self, row: int, column: int) -> None:
        """Darken the hovered bar (and show a pointer cursor)."""
        key = self._bar_key_at(row, column)
        if key == self._hovered_key:
            return
        self._restore_hover()
        if key is not None:
            bar = self._bars[key]
            bar["label"].setStyleSheet(
                self._bar_style(self._darken(bar["bg"]), bar["fg"])
            )
            self.timeline_table.viewport().setCursor(
                Qt.CursorShape.PointingHandCursor
            )
            self._hovered_key = key

    def _restore_hover(self) -> None:
        """Return the previously hovered bar to its base color."""
        if self._hovered_key is not None and self._hovered_key in self._bars:
            bar = self._bars[self._hovered_key]
            bar["label"].setStyleSheet(self._bar_style(bar["bg"], bar["fg"]))
        self._hovered_key = None
        self.timeline_table.viewport().unsetCursor()

    def _bar_key_at(self, row: int, column: int):
        """Return the ``(row, start_col)`` key of the bar covering a cell."""
        if (row, column) in self._bars:
            return (row, column)
        for col in range(column, -1, -1):
            if (row, col) in self._bars:
                span = self._bars[(row, col)]["span"]
                return (row, col) if col + span > column else None
        return None

    def eventFilter(self, obj, event):
        """Clear hover on leave; keep the today band sized to the viewport."""
        if obj is self.timeline_table.viewport():
            if event.type() == QEvent.Type.Leave:
                self._restore_hover()
            elif event.type() == QEvent.Type.Resize:
                self._update_today_overlay()
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------- Styling
    def _bar_style(self, bg: str, fg: str) -> str:
        """Stylesheet for an episode bar label in the given colors."""
        return (
            f"background: {bg}; color: {fg}; font-size: 11px;"
            " border-radius: 4px; margin: 2px; padding: 0 6px;"
        )

    def _darken(self, hex_color: str, factor: float = None) -> str:
        """Return ``hex_color`` multiplied toward black by ``factor``."""
        if factor is None:
            factor = self.HOVER_DARKEN
        try:
            h = (hex_color or "").lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except (ValueError, IndexError):
            return hex_color
        r = max(0, min(255, int(r * factor)))
        g = max(0, min(255, int(g * factor)))
        b = max(0, min(255, int(b * factor)))
        return f"#{r:02X}{g:02X}{b:02X}"

    # ----------------------------------------------------------- Data API
    def set_data(
        self,
        rows: list,
        min_date: date,
        max_date: date,
        floor_date: date = None,
    ) -> None:
        """Populate the chart.

        ``rows`` is a list of ``{"channel": str, "episodes": [episode]}`` where
        each episode is ``{"start", "end", "label", "status"}``.

        Only ``[min_date, max_date]`` is rendered initially. ``floor_date`` is
        the oldest date the chart may lazily scroll back to; older days are
        loaded ``PAST_LOAD_DAYS`` at a time as the user reaches the left edge.
        Defaults to ``min_date`` (no lazy history).
        """
        self._rows = rows
        self._max_date = max_date
        self._loaded_min = min_date
        self._floor = floor_date if floor_date is not None else min_date
        self._render()

    def _render(self) -> None:
        """(Re)build both tables for the currently loaded date window."""
        min_date = self._loaded_min
        max_date = self._max_date
        self._min_date = min_date

        days = self._build_day_list(min_date, max_date)
        day_index = {d: i for i, d in enumerate(days)}
        self._today_col = day_index.get(date.today())

        self._build_channel_table(self._rows)
        self._build_timeline_table(
            self._rows, days, day_index, min_date, max_date
        )

        self._timeline_header.set_today_col(
            self._today_col if self._today_col is not None else -1
        )
        self._update_today_overlay()

    def scroll_to_date(self, target: date, view_fraction: float = 0.75) -> None:
        """Scroll horizontally so ``target`` sits at ``view_fraction`` across."""
        if self._min_date is None or self._max_date is None:
            return
        if target < self._min_date or target > self._max_date:
            return

        days_until = (target - self._min_date).days
        target_pixel_x = days_until * self.DAY_WIDTH
        viewport_width = self.timeline_table.viewport().width()
        target_x = target_pixel_x - int(viewport_width * view_fraction)

        bar = self.timeline_table.horizontalScrollBar()
        target_x = max(0, min(target_x, bar.maximum()))
        bar.setValue(target_x)

    # ------------------------------------------------- Lazy history loading
    def _on_horizontal_scroll(self, value: int) -> None:
        """React to horizontal scrolling: keep the band aligned, load history."""
        self._update_today_overlay()
        self._maybe_load_past(value)

    def _on_vertical_scroll(self, _value: int) -> None:
        """Keep the today band spanning the full viewport while scrolling down."""
        self._update_today_overlay()

    def _maybe_load_past(self, value: int) -> None:
        """Load older history when the viewport nears the left edge."""
        if self._extending:
            return
        if self._loaded_min is None or self._floor is None:
            return
        if self._loaded_min <= self._floor:
            return  # nothing older to load

        bar = self.timeline_table.horizontalScrollBar()
        trigger = bar.minimum() + self.PAST_LOAD_TRIGGER_DAYS * self.DAY_WIDTH
        if value > trigger:
            return

        self._extend_past()

    def _extend_past(self) -> None:
        """Prepend another ``PAST_LOAD_DAYS`` of history, anchoring the view."""
        new_min = self._loaded_min - timedelta(days=self.PAST_LOAD_DAYS)
        if new_min < self._floor:
            new_min = self._floor
        added_days = (self._loaded_min - new_min).days
        if added_days <= 0:
            return

        self._extending = True
        try:
            bar = self.timeline_table.horizontalScrollBar()
            old_value = bar.value()
            self._loaded_min = new_min
            self._render()
            # New columns were prepended on the left, shifting existing content
            # right; offset the scrollbar by the same amount so the visible
            # dates stay put instead of jumping.
            bar.setValue(old_value + added_days * self.DAY_WIDTH)
        finally:
            self._extending = False

    def _update_today_overlay(self) -> None:
        """Resize the today band to the viewport and position it over today."""
        if self._today_overlay is None:
            return

        viewport = self.timeline_table.viewport()
        self._today_overlay.setGeometry(viewport.rect())

        if self._today_col is None or self._today_col < 0:
            self._today_overlay.set_column(None, 0)
            return

        x = self.timeline_table.columnViewportPosition(self._today_col)
        width = self.timeline_table.columnWidth(self._today_col)
        self._today_overlay.set_column(x, width)
        # Cell widgets (bar labels) are added after the overlay, so keep it on
        # top whenever we reposition it.
        self._today_overlay.raise_()

    # ------------------------------------------------------- Table builders
    def _build_channel_table(self, rows: list) -> None:
        self.channel_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            item = QTableWidgetItem(row["channel"])
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            )
            self.channel_table.setItem(r, 0, item)

    def _build_timeline_table(
        self, rows, days, day_index, min_date, max_date
    ) -> None:
        table = self.timeline_table
        # Fully tear down the previous render first. clearSpans() only drops the
        # spans and setRowCount/setColumnCount keep existing cells when the
        # counts are unchanged, so stale QLabel cell widgets from a previous
        # build would survive and show up as leftover single-day bars. Collapsing
        # to zero rows/columns destroys those cell widgets before we rebuild.
        table.clearSpans()
        table.setRowCount(0)
        table.setColumnCount(0)
        table.setRowCount(len(rows))
        table.setColumnCount(len(days))
        table.setHorizontalHeaderLabels(self._build_day_labels(days))

        # Forget bars from the previous render (their widgets are destroyed).
        self._bars = {}
        self._hovered_key = None

        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setDefaultSectionSize(self.DAY_WIDTH)
        # Top-align so the week label sits on the upper line and the day numbers
        # line up along the lower line across every cell.
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        for i in range(len(days)):
            table.setColumnWidth(i, self.DAY_WIDTH)

        # Full date as a tooltip on each day header (year, month, day, week).
        for i, d in enumerate(days):
            hitem = table.horizontalHeaderItem(i)
            if hitem is not None:
                week = d.isocalendar()[1]
                hitem.setToolTip(
                    f"{d:%A}, {d.day} {d:%B} {d.year} · Week {week}"
                )

        for r, row in enumerate(rows):
            for ep in row["episodes"]:
                self._place_episode(
                    table, r, ep, min_date, max_date, day_index
                )

    # -------------------------------------------------------------- Pieces
    def _place_episode(
        self, table, r, episode, min_date, max_date, day_index
    ) -> bool:
        """Add one episode bar to ``table`` at row ``r``."""
        start = episode["start"]
        end = episode["end"]
        if start is None or end is None:
            return False

        visible_start = max(start, min_date)
        visible_end = min(end, max_date)
        if visible_end < visible_start:
            return False

        start_col = day_index[visible_start]
        span = (visible_end - visible_start).days + 1

        if span > 1:
            table.setSpan(r, start_col, 1, span)

        # Color the bar by its project (falling back to status color).
        color = episode.get("color")
        if color:
            bg, fg = color
        else:
            bg, fg = CellStatus.color_for(episode["status"])

        label = QLabel(episode["label"] or "—")
        label.setWordWrap(False)
        # Quick tooltips for the bars too.
        label.setStyle(self._fast_tooltip_style)
        # Let clicks pass through to the cell so the row gets selected.
        label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        label.setStyleSheet(self._bar_style(bg, fg))
        tooltip_lines = [episode["label"] or "(no label)"]
        if episode.get("project"):
            tooltip_lines.append(f"Project: {episode['project']}")
        if episode["status"]:
            tooltip_lines.append(f"Status: {episode['status']}")
        tooltip_lines.append(
            f"Duration: {start.isoformat()} → {end.isoformat()}"
        )
        tooltip = "\n".join(tooltip_lines)
        label.setToolTip(tooltip)

        # Put a (transparent) item underneath so the tooltip still shows when
        # hovering the cell area around the mouse-transparent label, and so the
        # cell participates in row selection.
        item = QTableWidgetItem()
        item.setToolTip(tooltip)
        # Stash the full episode so a double-click can show its details. Store
        # the span too, so clicks anywhere across a multi-day bar resolve back
        # to this episode.
        item.setData(Qt.ItemDataRole.UserRole, episode)
        item.setData(Qt.ItemDataRole.UserRole + 1, span)
        table.setItem(r, start_col, item)

        table.setCellWidget(r, start_col, label)

        # Remember the bar so we can darken it on hover and restore it later.
        self._bars[(r, start_col)] = {
            "label": label,
            "bg": bg,
            "fg": fg,
            "span": span,
        }
        return True

    # -------------------------------------------------------------- Helpers
    def _build_day_labels(self, days: list) -> list:
        """Header text per day, as two layers: week on top, day below.

        Every cell has two lines so the day numbers stay aligned. The top line
        shows the ISO week number only on the first day of each week (blank
        otherwise). The bottom line shows the day of month, with the abbreviated
        month name appended at the start of each month (and the first day shown)
        so it reads like ``1 Jun``.
        """
        labels = []
        prev_week = None
        prev_month = None
        for d in days:
            week = d.isocalendar()[1]
            top = f"W{week}" if week != prev_week else ""
            prev_week = week

            if d.month != prev_month:
                prev_month = d.month
                bottom = f"{d.day} {d.strftime('%b')}"
            else:
                bottom = f"{d.day:02d}"

            labels.append(f"{top}\n{bottom}")
        return labels

    @staticmethod
    def _build_day_list(min_date, max_date) -> list:
        days = []
        current = min_date
        while current <= max_date:
            days.append(current)
            current += timedelta(days=1)
        return days







