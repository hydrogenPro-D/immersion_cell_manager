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
from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QRect, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QPainterPath, QLinearGradient

from src.data.enums import CellStatus

# Shared accent palette for the "today" highlight.
TODAY_ACCENT = "#3FA3A3"
TODAY_ACCENT_DARK = "#2C8585"

# Whole-row tint by the channel's current cell status. Colorblind-safe pairing
# (Okabe–Ito): a bluish green vs. an orange-red (vermillion), which differ on the
# blue-yellow axis and in lightness, so red-green colorblind users can tell them
# apart. RGBA so the wash sits behind the episode bars.
STATUS_ROW_TINTS = {
    "available": (0, 158, 115, 66),   # bluish green
    "in repair": (213, 94, 0, 68),    # vermillion / orange-red
}
# Solid tint for the channel-name cell on the left, same two statuses.
STATUS_NAME_TINTS = {
    "available": "#D3EFE6",  # light bluish green
    "in repair": "#F8DDC4",  # light vermillion
}


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


class _StatusRowOverlay(QWidget):
    """Transparent overlay painting per-row status tint bands over the grid.

    Kept lowered under the episode bars so the wash shows around them.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._bands = []  # list of (y, height, QColor)

    def set_bands(self, bands) -> None:
        self._bands = bands
        self.update()

    def paintEvent(self, event) -> None:
        if not self._bands:
            return
        painter = QPainter(self)
        width = self.width()
        for y, height, color in self._bands:
            painter.fillRect(QRect(0, y, width, height), color)


class _ExpectedExtension(QLabel):
    """Planned-end extension drawn past a bar's actual end.

    Painted by hand because Qt style sheets can't set dash spacing: the fill is
    the bar's own color at low opacity, and the outline is a sparse, translucent
    dashed stroke in the same color so it reads as a faint "planned" hint. The
    left edge is left flush and open (square corners, no border) so the shape
    reads as a continuation of the bar rather than a separate box.
    """

    RADIUS = 4

    def __init__(self, rgb, parent=None):
        super().__init__("", parent)
        self._rgb = rgb  # (r, g, b) of the parent bar

    def _shape(self, rect, closed: bool) -> QPainterPath:
        """Rect rounded on the right only. Open on the left when not closed."""
        rad = self.RADIUS
        path = QPainterPath()
        path.moveTo(rect.left(), rect.top())
        path.lineTo(rect.right() - rad, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + rad)
        path.lineTo(rect.right(), rect.bottom() - rad)
        path.quadTo(rect.right(), rect.bottom(), rect.right() - rad, rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        if closed:
            path.closeSubpath()  # fill needs the left edge; the outline omits it
        return path

    def paintEvent(self, event) -> None:
        r, g, b = self._rgb
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Flush on the left (x=0) so it butts against the bar; 2px top/bottom to
        # match the bar's margin; 2px on the right for the rounded cap.
        rect = QRectF(self.rect()).adjusted(0, 2, -2, -2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(r, g, b, 30))
        painter.drawPath(self._shape(rect, closed=True))
        pen = QPen(QColor(r, g, b, 140))
        pen.setWidthF(1.2)
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([3, 5])  # short dash, wide gap → sparse outline
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        outline = rect.adjusted(0, 0.6, -0.6, -0.6)  # inset so stroke isn't clipped
        painter.drawPath(self._shape(outline, closed=False))


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

    # Zoom scales row height + row/bar fonts (the day-column width stays fixed).
    BASE_ROW_HEIGHT = 30
    BASE_BAR_FONT = 11           # px, bar label text
    BASE_CHANNEL_FONT = 12       # px, channel-name text
    MIN_ZOOM = 0.7
    MAX_ZOOM = 2.0
    ZOOM_STEP = 0.10

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
        self._status_overlay = None
        # Lazy "load more history on scroll-left" state.
        self._rows = []
        self._loaded_min = None   # left edge currently rendered
        self._floor = None        # oldest date we may scroll back to
        self._extending = False   # re-entrancy guard while rebuilding
        self._rendering = False   # true while _render is building the tables
        self._syncing = False
        self._selecting = False
        # Every bar entry {"row","start_col","span","label","bg","fg"} in creation
        # order — the authoritative list for destroying/repositioning ALL bars
        # (multiple episodes can share a (row, start_col), so a dict alone would
        # drop the colliding ones and leak them as ghosts).
        self._bar_widgets = []
        # (row, start_col) -> the same entry, for hover lookup (last one wins).
        self._bars = {}
        self._hovered_key = None
        # Shared style that makes tooltips pop up quickly (kept as an attribute
        # so it isn't garbage-collected while widgets reference it).
        self._fast_tooltip_style = _FastTooltipStyle()
        # Zoom state (row height + fonts). ROW_HEIGHT shadows the class default so
        # every self.ROW_HEIGHT use picks up the zoomed value.
        self._zoom = 1.0
        self.ROW_HEIGHT = self.BASE_ROW_HEIGHT
        self._bar_font_px = self.BASE_BAR_FONT
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

        # Overlay tinting whole rows by the channel's current status. Created
        # first and kept lowered so episode bars render on top of the wash.
        self._status_overlay = _StatusRowOverlay(self.timeline_table.viewport())
        self._status_overlay.setGeometry(self.timeline_table.viewport().rect())
        self._status_overlay.lower()
        self._status_overlay.show()

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
        table.setAutoScroll(False)
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
                self._update_status_overlay()
                self._reposition_bars()
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------- Styling
    def _bar_style(self, bg: str, fg: str) -> str:
        """Stylesheet for an episode bar label in the given colors."""
        return (
            f"background: {bg}; color: {fg}; font-size: {self._bar_font_px}px;"
            " border: 1px solid #000000;"
            " border-radius: 4px; margin: 2px; padding: 0 6px;"
        )

    # --------------------------------------------------------------- Zoom
    def set_zoom(self, zoom: float) -> float:
        """Scale row height + row/bar fonts by ``zoom`` and re-render.

        The day-column width is intentionally left fixed. Returns the clamped
        zoom actually applied.
        """
        zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, zoom))
        self._zoom = zoom
        self.ROW_HEIGHT = round(self.BASE_ROW_HEIGHT * zoom)
        self._bar_font_px = max(7, round(self.BASE_BAR_FONT * zoom))

        for table in (self.timeline_table, self.channel_table):
            table.verticalHeader().setDefaultSectionSize(self.ROW_HEIGHT)
        cf = self.channel_table.font()
        cf.setPixelSize(max(8, round(self.BASE_CHANNEL_FONT * zoom)))
        self.channel_table.setFont(cf)

        # Rebuild so the new row height + bar font take effect, keeping the view.
        if self._min_date is not None:
            self.set_data(
                self._rows, self._loaded_min, self._max_date, self._floor,
                preserve_view=True,
            )
        return zoom

    def zoom_step(self, direction: int) -> float:
        """Zoom in (direction>0) or out (direction<0) by one step."""
        return self.set_zoom(self._zoom + direction * self.ZOOM_STEP)

    @staticmethod
    def _hex_rgb(hex_color: str):
        """Return ``(r, g, b)`` for a ``#RRGGBB`` string (teal on failure)."""
        h = (hex_color or "").lstrip("#")
        try:
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except (ValueError, IndexError):
            return 63, 163, 163

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
        preserve_view: bool = False,
    ) -> None:
        """Populate the chart.

        ``rows`` is a list of ``{"channel": str, "episodes": [episode]}`` where
        each episode is ``{"start", "end", "label", "status"}``.

        Only ``[min_date, max_date]`` is rendered initially. ``floor_date`` is
        the oldest date the chart may lazily scroll back to; older days are
        loaded ``PAST_LOAD_DAYS`` at a time as the user reaches the left edge.
        Defaults to ``min_date`` (no lazy history).

        With ``preserve_view`` the currently-loaded left edge and scroll offsets
        are kept, so a refresh doesn't snap the view back to today.
        """
        self._rows = rows
        self._max_date = max_date
        self._floor = floor_date if floor_date is not None else min_date

        if preserve_view and self._min_date is not None:
            hbar = self.timeline_table.horizontalScrollBar()
            vbar = self.timeline_table.verticalScrollBar()
            keep_h, keep_v = hbar.value(), vbar.value()
            # Keep the current left edge (it may be lazily extended into the past).
            self._render()
            # Restore scroll + bar positions synchronously, so no event-loop tick
            # paints the reset (scroll=0) state — avoids a one-frame flash.
            # executeDelayedItemsLayout forces the rebuilt table's scrollbar range
            # to be final first, so setValue isn't clamped against a stale maximum.
            self._rendering = True  # suppress lazy past-load during the restore
            try:
                # Finalize the rebuilt table's scrollbar range, then restore scroll.
                self.timeline_table.executeDelayedItemsLayout()
                self.channel_table.executeDelayedItemsLayout()
                hbar.setValue(min(keep_h, hbar.maximum()))
                vbar.setValue(min(keep_v, vbar.maximum()))
                # The rebuild leaves the header offsets stuck at 0 while the
                # scrollbars hold the restored values, so the grid/date-axis would
                # paint at the wrong scroll (bars right, dates wrong). Push the
                # scroll values into the header offsets — what a resize does
                # internally — so grid, overlays and bars share one scroll.
                self.timeline_table.horizontalHeader().setOffset(hbar.value())
                self.timeline_table.verticalHeader().setOffset(vbar.value())
                self.channel_table.verticalHeader().setOffset(
                    self.channel_table.verticalScrollBar().value()
                )
                self._reposition_bars()
            finally:
                self._rendering = False
            self._update_today_overlay()
            self._update_status_overlay()
            self.timeline_table.viewport().update()
            return

        self._loaded_min = min_date
        self._render()

    def _render(self) -> None:
        """(Re)build both tables for the currently loaded date window."""
        # Re-entrancy guard: building the table moves the scrollbar, which fires
        # valueChanged -> _maybe_load_past synchronously. Without this it could
        # rebuild the table mid-render and corrupt the bar spans.
        self._rendering = True
        try:
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

            # The rebuild reset the scrollbars to 0 with signals blocked, leaving
            # the header offsets stuck at the pre-rebuild scroll. Push the scroll
            # values back into the offsets so the grid/date axis (positioned via
            # columnViewportPosition -> header offset) and the bars (positioned via
            # the scrollbar value) share one offset. Without this the bars misalign
            # with the grid and the today marker lands off-screen after a filter.
            self.timeline_table.horizontalHeader().setOffset(
                self.timeline_table.horizontalScrollBar().value()
            )
            self.timeline_table.verticalHeader().setOffset(
                self.timeline_table.verticalScrollBar().value()
            )
            self.channel_table.verticalHeader().setOffset(
                self.channel_table.verticalScrollBar().value()
            )

            self._timeline_header.set_today_col(
                self._today_col if self._today_col is not None else -1
            )
            self._update_today_overlay()
            self._update_status_overlay()
            self._reposition_bars()
        finally:
            self._rendering = False

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
        # After a rebuild the scrollbar range isn't final yet, so clamping against
        # a stale maximum would pin the view to the far left. Force the range to
        # settle first (same fix the preserve-view restore uses).
        self.timeline_table.executeDelayedItemsLayout()
        target_x = max(0, min(target_x, bar.maximum()))
        bar.setValue(target_x)
        # After a rebuild Qt defers the header-offset update (scrollContentsBy), so
        # setValue moves our bars (via _on_horizontal_scroll) while the date grid
        # stays at the old offset — they disagree by the scroll amount. Force the
        # offset to match now and repaint, mirroring the preserve-view restore.
        self.timeline_table.horizontalHeader().setOffset(bar.value())
        self._reposition_bars()
        self._update_today_overlay()
        self._update_status_overlay()
        self.timeline_table.viewport().update()

    # ------------------------------------------------- Lazy history loading
    def _on_horizontal_scroll(self, value: int) -> None:
        """React to horizontal scrolling: keep the bands aligned, load history."""
        self._update_today_overlay()
        self._update_status_overlay()
        self._reposition_bars()
        self._maybe_load_past(value)

    def _on_vertical_scroll(self, _value: int) -> None:
        """Keep the today band spanning the full viewport while scrolling down."""
        self._update_today_overlay()
        self._update_status_overlay()
        self._reposition_bars()

    def _maybe_load_past(self, value: int) -> None:
        """Load older history when the viewport nears the left edge."""
        if self._extending or self._rendering:
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

    def _reposition_bars(self) -> None:
        """Place every bar (a viewport child we own) at its cell's viewport rect.

        Computed directly from DAY_WIDTH/ROW_HEIGHT and the scroll offsets. Called
        on every render, scroll and resize, so the bars always track the grid.
        """
        hoff = self.timeline_table.horizontalScrollBar().value()
        voff = self.timeline_table.verticalScrollBar().value()
        for bar in self._bar_widgets:
            label = bar.get("label")
            if label is None:
                continue
            x = bar["start_col"] * self.DAY_WIDTH - hoff
            y = bar["row"] * self.ROW_HEIGHT - voff
            label.setGeometry(x, y, bar["span"] * self.DAY_WIDTH, self.ROW_HEIGHT)

    def _update_status_overlay(self) -> None:
        """Resize the status overlay and rebuild its per-row tint bands."""
        overlay = self._status_overlay
        if overlay is None:
            return
        viewport = self.timeline_table.viewport()
        overlay.setGeometry(viewport.rect())

        bands = []
        for r, row in enumerate(self._rows):
            tint = STATUS_ROW_TINTS.get((row.get("status") or "").strip().lower())
            if tint is None:
                continue
            y = self.timeline_table.rowViewportPosition(r)
            h = self.timeline_table.rowHeight(r)
            if h <= 0 or y + h < 0 or y > viewport.height():
                continue  # off-screen row
            bands.append((y, h, self._opaque_status_color(tint)))
        overlay.set_bands(bands)
        overlay.lower()  # keep under the bars

    @staticmethod
    def _opaque_status_color(rgba) -> QColor:
        """Flatten an RGBA row tint over the table's white base into a solid color.

        Filling the band opaquely keeps a status (red / green) row the same shade
        regardless of the alternating zebra colour underneath it.
        """
        r, g, b, a = rgba
        f = a / 255.0
        return QColor(
            round(r * f + 255 * (1 - f)),
            round(g * f + 255 * (1 - f)),
            round(b * f + 255 * (1 - f)),
        )

    # ------------------------------------------------------- Table builders
    def _build_channel_table(self, rows: list) -> None:
        self.channel_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            item = QTableWidgetItem(row["channel"])
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            )
            tint = STATUS_NAME_TINTS.get((row.get("status") or "").strip().lower())
            if tint:
                item.setBackground(QColor(tint))
            self.channel_table.setItem(r, 0, item)

    def _build_timeline_table(
        self, rows, days, day_index, min_date, max_date
    ) -> None:
        table = self.timeline_table
        # Remove the previous render's bar widgets up front (viewport children we
        # own; setRowCount(0) won't drop them). Clear self._bars BEFORE anything
        # else so a stray _reposition_bars can't touch a pending-delete label.
        for bar in self._bar_widgets:
            lbl = bar.get("label")
            if lbl is not None:
                lbl.hide()
                lbl.deleteLater()
        self._bar_widgets = []
        self._bars = {}
        self._hovered_key = None

        # Tear down the previous render's rows/columns. Block the scrollbar's
        # signals while the counts change so the emitted valueChanged can't
        # trigger lazy loading in the middle of a build.
        hbar = table.horizontalScrollBar()
        hbar.blockSignals(True)
        try:
            table.clearSpans()
            table.setRowCount(0)
            table.setColumnCount(0)
            table.setRowCount(len(rows))
            table.setColumnCount(len(days))
        finally:
            hbar.blockSignals(False)
        table.setHorizontalHeaderLabels(self._build_day_labels(days))

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
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
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

        # Parent the bar to the viewport and manage its geometry ourselves (see
        # _reposition_bars) instead of setCellWidget: Qt owns the geometry of
        # index widgets and re-places them from columnViewportPosition, which
        # lags the scrollbar after a rebuild — so it kept shoving bars into the
        # future until a resize. As our own child, nothing overrides us.
        label.setParent(table.viewport())
        label.show()

        # Track the bar. The list holds every bar (so all get destroyed and
        # repositioned even when several share a (row, start_col)); the dict is
        # for hover lookup, where last-one-at-a-key wins.
        entry = {
            "row": r,
            "start_col": start_col,
            "span": span,
            "label": label,
            "bg": bg,
            "fg": fg,
        }
        self._bar_widgets.append(entry)
        self._bars[(r, start_col)] = entry

        # Dashed extension out to the planned (expected) end date, when it's
        # beyond the bar's actual end and within the loaded window.
        expected = episode.get("expected_end")
        if expected is not None and expected > visible_end:
            ext_start = visible_end + timedelta(days=1)
            ext_end = min(expected, max_date)
            if ext_end >= ext_start and ext_start in day_index:
                ext_col = day_index[ext_start]
                ext_span = (ext_end - ext_start).days + 1
                ext = _ExpectedExtension(self._hex_rgb(bg))
                ext.setStyle(self._fast_tooltip_style)
                ext.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
                )
                ext.setToolTip(f"Expected end: {expected.isoformat()}")
                ext.setParent(table.viewport())
                ext.show()
                self._bar_widgets.append({
                    "row": r, "start_col": ext_col, "span": ext_span,
                    "label": ext, "bg": bg, "fg": fg,
                })
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







