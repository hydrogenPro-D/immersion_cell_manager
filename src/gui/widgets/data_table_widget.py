from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
import re

from PyQt6.QtWidgets import QTableWidget, QTableView, QAbstractItemView, QHeaderView, QGraphicsDropShadowEffect, QTableWidgetItem

from src.gui.styles.table_styles import TABLE_STYLE
from src.gui.widgets.pill_delegate import PillDelegate


class DataTableWidget(QTableWidget):
    """Custom table widget for displaying and managing data"""

    # Comment text wrapping configuration
    COMMENT_WRAP_LENGTH = 60

    # Zoom scales the cell font + row height together.
    BASE_ROW_HEIGHT = 40
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

        # Selection / editing behaviour
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
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
        h_header.setHighlightSections(False)
        h_header.setDefaultAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        h_header.setFixedHeight(44)
        # Connect header click for custom sorting
        h_header.sectionClicked.connect(self._on_header_clicked)

        # Vertical header polish
        v_header = self.verticalHeader()
        v_header.setDefaultSectionSize(40)
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
        self.frozen_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.frozen_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
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

        # Let PyQt auto-resize row to fit content
        self.resizeRowToContents(row_position)

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
        get_spec = getattr(self.manager, "get_field_spec", None)
        if not callable(get_spec):
            return

        for col, name in enumerate(self.manager.get_column_names()):
            spec = get_spec(name)
            resolver = getattr(spec, "color_resolver", None)
            if resolver is None:
                continue
            self.setItemDelegateForColumn(col, PillDelegate(resolver, self))
            # Mirror the delegate on the frozen overlay for the first column
            if col == 0 and hasattr(self, "frozen_view"):
                self.frozen_view.setItemDelegateForColumn(
                    0, PillDelegate(resolver, self.frozen_view)
                )

