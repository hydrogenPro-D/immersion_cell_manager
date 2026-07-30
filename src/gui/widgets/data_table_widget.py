from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush
import re

from PyQt6.QtWidgets import (
    QTableWidget, QTableView, QAbstractItemView, QHeaderView,
    QGraphicsDropShadowEffect, QTableWidgetItem, QStyledItemDelegate,
    QStyle, QStyleOptionViewItem,
)

from src.gui.styles.table_styles import TABLE_STYLE
from src.gui.widgets.pill_delegate import PillDelegate, WARN_ROLE


class _RowTintDelegate(QStyledItemDelegate):
    """Paints an item's own background (a row tint set via ``setBackground``).

    The table stylesheet styles ``::item``, which makes Qt ignore the model's
    background role — so a plain cell can't be tinted by ``setBackground`` alone.
    This delegate fills the tint itself (bypassing the stylesheet) and lets the
    base delegate draw only the text on top; untinted cells fall through to
    normal stylesheet rendering (alternating / hover / selection preserved).
    """

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        # Never highlight a cell on hover.
        opt.state &= ~QStyle.StateFlag.State_MouseOver
        brush = index.data(Qt.ItemDataRole.BackgroundRole)
        if brush is not None and not (opt.state & QStyle.StateFlag.State_Selected):
            painter.fillRect(option.rect, brush)
            # Drop the alternate feature / bg so the base delegate doesn't repaint
            # a (stylesheet) background over our fill.
            opt.features &= ~QStyleOptionViewItem.ViewItemFeature.Alternate
            opt.backgroundBrush = QBrush(Qt.GlobalColor.transparent)
        super().paint(painter, opt, index)

# Tooltip shown on the red "!" of a channel whose calibration is too old.
STALE_CALIBRATION_TOOLTIP = (
    "This channel hasn't been calibrated in over 3 months. Recalibrate it "
    "before setting it In use."
)

# Row tint for a channel whose calibration is Awaiting decision (matches the
# "Awaiting decision" pill background in the Channel Calibration tab).
PENDING_CALIBRATION_TINT = "#FFEAB3"


class DataTableWidget(QTableWidget):
    """Custom table widget for displaying and managing data"""

    # Comment text wrapping configuration
    COMMENT_WRAP_LENGTH = 60

    # Comments fills the leftover width but never shrinks below this (px), so it
    # stays readable even when the other columns fill the viewport.
    MIN_COMMENTS_WIDTH = 300

    # Extra px added to a wrapped (multi-line) row so the lines aren't cramped.
    MULTILINE_ROW_EXTRA = 4

    # Zoom scales the cell font + row height together.
    BASE_ROW_HEIGHT = 24
    BASE_FONT_PX = 12
    MIN_ZOOM = 0.7
    MAX_ZOOM = 2.0
    ZOOM_STEP = 0.10

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._zoom = 1.0
        self.sorted_column = None
        self.sort_order = None
        # Channels whose latest calibration is too old (get a red "!" on Status).
        self._stale_channels = set()
        # Channels with a calibration awaiting decision (whole row tinted yellow).
        self._pending_channels = set()
        # Get the projects manager to look up descriptions
        from src.data.immersion_cells_manager import ImmersionCellsManager
        if isinstance(manager, ImmersionCellsManager):
            self.projects_manager = manager.get_projects_manager()
        else:
            self.projects_manager = None
        self.init_table()
        self._install_column_delegates()

    def init_table(self):
        """Initialize the table widget with settings and styling"""
        # Set column count and headers
        self.setColumnCount(len(self.manager.get_column_names()))
        self.setHorizontalHeaderLabels(self.manager.get_column_names())

        # Hide the "Start hour" column - it's managed internally by the date picker
        try:
            start_hour_col = self.manager.get_column_names().index("Start hour")
            self.setColumnHidden(start_hour_col, True)
        except ValueError:
            pass  # Column doesn't exist yet, skip

        # Apply styling (font-size is zoom-dependent, so build it dynamically)
        self._apply_table_style()

        # Selection / editing behaviour. No selection: clicking a row shouldn't
        # highlight it (double-click still edits — it uses the clicked index).
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Enable scrollbars
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.setAlternatingRowColors(True)
        self.setMouseTracking(True)
        self.setShowGrid(False)
        self.setWordWrap(True)
        self.setCornerButtonEnabled(False)

        # Horizontal header polish
        h_header = self.horizontalHeader()
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        h_header.setMinimumSectionSize(100)  # Minimum width per column
        # Comments absorbs leftover width (fills the viewport) but is kept at
        # MIN_COMMENTS_WIDTH or wider by _fit_comments_column so it stays readable
        # even when the other columns are wide (a scrollbar appears instead).
        self._comments_col = None
        try:
            self._comments_col = self.manager.get_column_names().index("Comments")
            h_header.setSectionResizeMode(
                self._comments_col, QHeaderView.ResizeMode.Interactive
            )
            h_header.sectionResized.connect(self._on_section_resized)
        except (ValueError, AttributeError):
            h_header.setStretchLastSection(True)
        h_header.setHighlightSections(False)
        h_header.setDefaultAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        h_header.setFixedHeight(44)
        # Connect header click for custom sorting
        h_header.sectionClicked.connect(self._on_header_clicked)

        # Vertical header polish
        v_header = self.verticalHeader()
        v_header.setDefaultSectionSize(self.BASE_ROW_HEIGHT)
        # Let single-line rows shrink to their content (the default minimum
        # floors them taller than needed).
        v_header.setMinimumSectionSize(16)
        v_header.setVisible(False)

        # Subtle elevated shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(20, 50, 70, 45))
        self.setGraphicsEffect(shadow)

        # Frozen first column overlay
        self._init_frozen_column()

    # ------------------------------------------------------------------
    # Zoom (row height + font)
    # ------------------------------------------------------------------
    def _font_px(self) -> int:
        return max(8, round(self.BASE_FONT_PX * self._zoom))

    def _apply_table_style(self) -> None:
        """(Re)apply the main table stylesheet with the current zoom font size.

        The widget QFont is set to the same size too: the stylesheet governs
        painting, but row auto-fit (resizeRowToContents) sizes from the QFont, so
        both must agree or rows would clip the text.
        """
        fs = self._font_px()
        self.setStyleSheet(TABLE_STYLE + f"""
            QTableWidget::item:focus {{ outline: none; border: none; }}
            QTableWidget {{ font-size: {fs}px; }}
            QTableWidget::item {{ font-size: {fs}px; }}
        """)
        f = self.font()
        f.setPixelSize(fs)
        self.setFont(f)

    def _apply_frozen_style(self) -> None:
        """(Re)apply the frozen column overlay stylesheet at the current zoom."""
        if not hasattr(self, "frozen_view"):
            return
        fs = self._font_px()
        self.frozen_view.setStyleSheet(
            TABLE_STYLE.replace("QTableWidget", "QTableView") + f"""
            QTableView {{
                margin: 0px;
                border: none;
                border-right: 1px solid #D8E2E8;
                border-top-left-radius: 12px;
                background-color: #FFFFFF;
                font-size: {fs}px;
            }}
            QTableView::item {{ font-size: {fs}px; }}
            QTableView::item:focus {{ outline: none; border: none; }}
            QHeaderView::section:last {{
                border-top-right-radius: 0px;
                border-right: 1px solid rgba(255, 255, 255, 0.18);
            }}
        """)
        f = self.frozen_view.font()
        f.setPixelSize(fs)
        self.frozen_view.setFont(f)

    def set_zoom(self, zoom: float) -> float:
        """Scale the cell font + row height by ``zoom``. Returns the clamped value."""
        zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, zoom))
        self._zoom = zoom
        self._apply_table_style()
        self._apply_frozen_style()
        row_min = round(self.BASE_ROW_HEIGHT * zoom)
        self.verticalHeader().setDefaultSectionSize(row_min)
        if hasattr(self, "frozen_view"):
            self.frozen_view.verticalHeader().setDefaultSectionSize(row_min)
        # Re-fit existing rows to the new font (frozen rows follow via sectionResized).
        self.resizeRowsToContents()
        return zoom

    def zoom_step(self, direction: int) -> float:
        """Zoom in (direction>0) or out (direction<0) by one step."""
        return self.set_zoom(self._zoom + direction * self.ZOOM_STEP)

    # ------------------------------------------------------------------
    # Frozen first column
    # ------------------------------------------------------------------
    def _init_frozen_column(self):
        """Create an overlay view pinned to the left that mirrors column 0.

        The overlay shares the model and selection model with the main
        table, so data, sorting and row selection stay in sync while the
        first column remains visible during horizontal scrolling.
        """
        self.frozen_view = QTableView(self)
        self.frozen_view.setModel(self.model())
        self.frozen_view.setSelectionModel(self.selectionModel())
        self.frozen_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.frozen_view.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.frozen_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.frozen_view.setAlternatingRowColors(True)
        self.frozen_view.setShowGrid(False)
        self.frozen_view.setWordWrap(True)
        self.frozen_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.frozen_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Match the main table look, but drop the outer margin/border so the
        # overlay sits flush inside the main table frame. (Font-size is zoomable.)
        self._apply_frozen_style()

        # Frozen header mirrors the main header and forwards sort clicks
        f_header = self.frozen_view.horizontalHeader()
        f_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        f_header.setHighlightSections(False)
        f_header.setDefaultAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        f_header.setFixedHeight(self.horizontalHeader().height())
        f_header.setSectionsClickable(True)
        f_header.sectionClicked.connect(self._on_header_clicked)

        f_v_header = self.frozen_view.verticalHeader()
        f_v_header.setDefaultSectionSize(self.verticalHeader().defaultSectionSize())
        # Match the main table's minimum so synced row heights don't get floored
        # taller here (which would misalign the frozen Channel column).
        f_v_header.setMinimumSectionSize(16)
        f_v_header.setVisible(False)

        # Only show the first column
        for col in range(1, self.columnCount()):
            self.frozen_view.setColumnHidden(col, True)
        self.frozen_view.setColumnWidth(0, self.columnWidth(0))

        # Keep the overlay above the main viewport
        self.viewport().stackUnder(self.frozen_view)

        # Forward interactions to the main table (shared model => same indexes)
        self.frozen_view.doubleClicked.connect(self.doubleClicked)
        self.frozen_view.clicked.connect(self.clicked)

        # Keep widths, row heights and scrolling in sync
        self.horizontalHeader().sectionResized.connect(self._on_frozen_section_resized)
        self.verticalHeader().sectionResized.connect(self._on_frozen_row_resized)
        self.verticalScrollBar().valueChanged.connect(self.frozen_view.verticalScrollBar().setValue)
        self.frozen_view.verticalScrollBar().valueChanged.connect(self.verticalScrollBar().setValue)

        self._update_frozen_geometry()
        self.frozen_view.show()

    def _on_frozen_section_resized(self, logical_index: int, old_size: int, new_size: int):
        """Mirror width changes of column 0 onto the frozen view."""
        if logical_index == 0:
            self.frozen_view.setColumnWidth(0, new_size)
            self._update_frozen_geometry()

    def _on_frozen_row_resized(self, logical_index: int, old_size: int, new_size: int):
        """Mirror row height changes onto the frozen view."""
        self.frozen_view.setRowHeight(logical_index, new_size)

    def _update_frozen_geometry(self):
        """Position the frozen view over column 0, covering header + rows."""
        viewport_geo = self.viewport().geometry()
        header_height = self.horizontalHeader().height()
        self.frozen_view.setGeometry(
            viewport_geo.x(),
            viewport_geo.y() - header_height,
            self.columnWidth(0),
            header_height + viewport_geo.height(),
        )

    def _on_section_resized(self, logical_index, _old, _new):
        # A content-sized column changed width -> re-fit Comments. Ignore our own
        # resize of the Comments column to avoid a feedback loop.
        if logical_index != self._comments_col:
            self._fit_comments_column()

    def _fit_comments_column(self):
        """Size Comments to the leftover width, floored at MIN_COMMENTS_WIDTH."""
        col = getattr(self, "_comments_col", None)
        if col is None:
            return
        others = sum(
            self.columnWidth(c) for c in range(self.columnCount())
            if c != col and not self.isColumnHidden(c)
        )
        leftover = self.viewport().width() - others
        target = max(self.MIN_COMMENTS_WIDTH, leftover)
        if self.columnWidth(col) != target:
            self.setColumnWidth(col, target)
            # Row heights were computed at the old (often narrower) width, which
            # over-wraps long comments into extra lines — re-fit to the new width.
            self.resizeRowsToContents()
            self._pad_multiline_rows()

    def _pad_multiline_row(self, row):
        """Give a wrapped (multi-line) row a few extra px so it isn't cramped."""
        single = self.fontMetrics().height() + 8  # ~ a single-line row height
        h = self.rowHeight(row)
        if h > single:
            self.setRowHeight(row, h + self.MULTILINE_ROW_EXTRA)

    def _pad_multiline_rows(self):
        for r in range(self.rowCount()):
            self._pad_multiline_row(r)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_comments_column()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_comments_column()
        if hasattr(self, "frozen_view"):
            self._update_frozen_geometry()

    def add_row(self, data):
        """Add a row to the table"""
        row_position = self.rowCount()
        self.insertRow(row_position)

        column_names = self.manager.get_column_names()
        for column, value in enumerate(data):
            text = str(value) if value is not None else ""

            # Get column name to check if it's Comments or Project ID
            column_name = (
                column_names[column]
                if column < len(column_names)
                else ""
            )

            # Wrap long text in Comments column
            if column_name == "Comments" and len(text) > self.COMMENT_WRAP_LENGTH:
                text = self._wrap_text(text, max_length=self.COMMENT_WRAP_LENGTH)

            item = QTableWidgetItem(text)
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
            )
            self.setItem(row_position, column, item)

        self._mark_stale_calibration(row_position, data, column_names)
        self._tint_pending_calibration(row_position, data, column_names)

        # Let PyQt auto-resize row to fit content, plus a little extra when the
        # row wraps to multiple lines so the lines aren't cramped.
        self.resizeRowToContents(row_position)
        self._pad_multiline_row(row_position)

    def set_stale_channels(self, channels) -> None:
        """Set which channels should show the stale-calibration warning."""
        self._stale_channels = set(channels or ())

    def set_pending_channels(self, channels) -> None:
        """Set which channels have a calibration awaiting decision (row tint)."""
        self._pending_channels = set(channels or ())

    def _tint_pending_calibration(self, row, data, column_names):
        """Tint the whole row yellow if its channel has a pending calibration."""
        if not self._pending_channels:
            return
        try:
            channel_col = column_names.index("Channel")
        except ValueError:
            return
        channel = str(data[channel_col]) if channel_col < len(data) else ""
        if channel not in self._pending_channels:
            return
        tint = QColor(PENDING_CALIBRATION_TINT)
        for c in range(self.columnCount()):
            item = self.item(row, c)
            if item is None:  # empty cells still need an item to carry the tint
                item = QTableWidgetItem("")
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
                )
                self.setItem(row, c, item)
            item.setBackground(tint)

    def _mark_stale_calibration(self, row, data, column_names):
        """Flag the Status cell with a red '!' if this row's channel is stale."""
        if not self._stale_channels:
            return
        try:
            channel_col = column_names.index("Channel")
            status_col = column_names.index("Status")
        except ValueError:
            return
        channel = str(data[channel_col]) if channel_col < len(data) else ""
        item = self.item(row, status_col)
        if item is not None and channel in self._stale_channels:
            item.setData(WARN_ROLE, True)
            item.setToolTip(STALE_CALIBRATION_TOOLTIP)

    def _wrap_text(self, text: str, max_length: int = None) -> str:
        """Wrap text to fit within max_length per line.

        Breaks text at word boundaries to avoid splitting words.
        Uses newline character to create line breaks.
        """
        if max_length is None:
            max_length = self.COMMENT_WRAP_LENGTH

        words = text.split()
        lines = []
        current_line = []
        current_length = 0

        for word in words:
            word_length = len(word)
            # Add 1 for the space between words
            if current_length + word_length + 1 <= max_length:
                current_line.append(word)
                current_length += word_length + 1
            else:
                # Start a new line
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
                current_length = word_length

        # Add the last line
        if current_line:
            lines.append(" ".join(current_line))

        return "\n".join(lines)

    def mouseMoveEvent(self, event):
        """Show tooltip for Project ID column items on hover."""
        item = self.itemAt(event.pos())
        if item and self.projects_manager:
            column_names = self.manager.get_column_names()
            column_index = self.column(item)

            if column_index < len(column_names) and column_names[column_index] == "Project ID":
                project_name = item.text().strip()
                if project_name:
                    description = self.projects_manager.get_description(project_name)
                    if description:
                        item.setToolTip(description)
                        return

        super().mouseMoveEvent(event)

    def _on_header_clicked(self, column: int):
        """Handle header click for sorting with cycle: asc -> desc -> no sort"""
        # Check if we're clicking the same column
        if self.sorted_column == column:
            # Cycle through sort orders
            if self.sort_order == Qt.SortOrder.AscendingOrder:
                # Switch to descending
                self.sort_order = Qt.SortOrder.DescendingOrder
                self._apply_sort(column, self.sort_order)
            else:
                # Switch to no sort (reset to default CSV order)
                self.sorted_column = None
                self.sort_order = None
                self._clear_sort_indicators()
                self._reset_to_default_order()
        else:
            # New column clicked, start with ascending
            self.sorted_column = column
            self.sort_order = Qt.SortOrder.AscendingOrder
            self._apply_sort(column, self.sort_order)

    def _apply_sort(self, column: int, order: Qt.SortOrder):
        """Sort the table by the given column and order"""
        # Check if this column needs special sorting
        column_name = self.horizontalHeaderItem(column).text().replace(" ▲", "").replace(" ▼", "")

        if column_name == "Channel":
            self._apply_custom_sort(column, order, self._extract_channel_numbers)
        elif column_name == "Added water by timing":
            self._apply_custom_sort(column, order, self._extract_numeric_value)
        elif column_name == "Duration":
            self._apply_custom_sort(column, order, self._extract_numeric_value)
        else:
            self.sortItems(column, order)

        self._update_sort_indicators(column, order)

    def _clear_sort_indicators(self):
        """Remove sort indicators from all column headers"""
        header = self.horizontalHeader()
        for col in range(self.columnCount()):
            label = self.horizontalHeaderItem(col)
            if label:
                text = label.text()
                # Remove any existing indicators
                text = text.replace(" ▲", "").replace(" ▼", "")
                label.setText(text)

    def _update_sort_indicators(self, column: int, order: Qt.SortOrder):
        """Update the visual indicator on the header for the sorted column"""
        self._clear_sort_indicators()

        header_item = self.horizontalHeaderItem(column)
        if header_item:
            text = header_item.text()
            # Remove indicators if they exist
            text = text.replace(" ▲", "").replace(" ▼", "")
            # Add the appropriate indicator (clean triangle arrows)
            indicator = " ▲" if order == Qt.SortOrder.AscendingOrder else " ▼"
            header_item.setText(text + indicator)

    def _reset_to_default_order(self):
        """Reset table to original CSV order by reloading all data"""
        # Store current selection
        selected_rows = self.selectionModel().selectedRows()
        selected_row_data = None
        if selected_rows:
            selected_row = selected_rows[0].row()
            selected_row_data = [
                self.item(selected_row, col).text()
                for col in range(self.columnCount())
            ]

        # Clear and reload all data in original order
        self.setRowCount(0)
        try:
            table_data = self.manager.get_table_data()
            for row_data in table_data:
                self.add_row(row_data)
        except Exception as e:
            print(f"Error resetting table order: {e}")

        # Restore selection if possible
        if selected_row_data:
            for row in range(self.rowCount()):
                row_data = [
                    self.item(row, col).text()
                    for col in range(self.columnCount())
                ]
                if row_data == selected_row_data:
                    self.selectRow(row)
                    break

    def resort_if_needed(self):
        """Re-sort the table if a sort is currently active.

        Call this after data changes to ensure the table remains sorted correctly.
        """
        if self.sorted_column is not None and self.sort_order is not None:
            self._apply_sort(self.sorted_column, self.sort_order)

    # ------------------------------------------------------------------
    def _extract_numeric_value(self, text: str) -> float:
        """Extract numeric value from text like '150 ml'.

        Returns the numeric value, or float('inf') if no number found (sorts to end).
        """
        try:
            # Extract first number (integer or float) from the text
            match = re.search(r'-?\d+(?:\.\d+)?', text)
            if match:
                return float(match.group())
        except (ValueError, AttributeError):
            pass
        return float('inf')  # Non-numeric values sort to the end

    def _extract_channel_numbers(self, text: str) -> tuple:
        """Extract channel numbers from text like '1-2' or '12-34'.

        Returns a tuple (first_num, second_num) for sorting by first number, then second.
        Returns (inf, inf) for invalid formats (sorts to end).
        """
        try:
            # Match pattern like "number-number"
            match = re.match(r'^(\d+)-(\d+)$', text.strip())
            if match:
                first = int(match.group(1))
                second = int(match.group(2))
                return (first, second)
        except (ValueError, AttributeError):
            pass
        return (float('inf'), float('inf'))  # Invalid formats sort to the end

    def _apply_custom_sort(self, column: int, order: Qt.SortOrder, key_func):
        """Sort the table using a custom key function.

        Args:
            column: Column index to sort by
            order: Qt.SortOrder.AscendingOrder or DescendingOrder
            key_func: Function that takes a string and returns a sortable value
        """
        # Collect all rows with their data
        rows = []
        for row in range(self.rowCount()):
            row_data = []
            for col in range(self.columnCount()):
                item = self.item(row, col)
                row_data.append(item.text() if item else "")
            rows.append(row_data)

        # Sort rows using the key function on the specified column
        reverse = order == Qt.SortOrder.DescendingOrder
        rows.sort(key=lambda x: key_func(x[column]), reverse=reverse)

        # Rebuild the table with sorted data
        # Store current selection
        selected_rows = self.selectionModel().selectedRows()
        selected_row_data = None
        if selected_rows:
            selected_row = selected_rows[0].row()
            selected_row_data = [self.item(selected_row, col).text() for col in range(self.columnCount())]

        # Clear all rows and re-add them in sorted order
        self.setRowCount(0)
        for row_data in rows:
            self.add_row(row_data)

        # Restore selection if possible
        if selected_row_data:
            for row in range(self.rowCount()):
                row_data = [self.item(row, col).text() for col in range(self.columnCount())]
                if row_data == selected_row_data:
                    self.selectRow(row)
                    break

    # ------------------------------------------------------------------
    def _install_column_delegates(self):
        """Install pill delegates for columns whose FieldSpec has colors.

        The manager is expected to expose ``get_field_spec(name)`` returning a
        :class:`FieldSpec`. If the spec carries a ``color_resolver`` the
        corresponding column gets a :class:`PillDelegate`. Missing methods or
        specs are silently ignored, so legacy managers keep working.
        """
        # Default delegate that honors a row tint (bypassing the ::item
        # stylesheet). Pill columns override it per-column below.
        self.setItemDelegate(_RowTintDelegate(self))
        if hasattr(self, "frozen_view"):
            self.frozen_view.setItemDelegate(_RowTintDelegate(self.frozen_view))

        get_spec = getattr(self.manager, "get_field_spec", None)
        if not callable(get_spec):
            return

        for col, name in enumerate(self.manager.get_column_names()):
            spec = get_spec(name)
            resolver = getattr(spec, "color_resolver", None)
            if resolver is None:
                continue
            self.setItemDelegateForColumn(
                col, PillDelegate(resolver, self, enable_hover=False)
            )
            # Mirror the delegate on the frozen overlay for the first column
            if col == 0 and hasattr(self, "frozen_view"):
                self.frozen_view.setItemDelegateForColumn(
                    0, PillDelegate(resolver, self.frozen_view, enable_hover=False)
                )

