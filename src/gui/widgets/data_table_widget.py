from PyQt6.QtWidgets import (
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QGraphicsDropShadowEffect,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
import re
from src.gui.styles.table_styles import TABLE_STYLE
from src.gui.widgets.pill_delegate import PillDelegate


class DataTableWidget(QTableWidget):
    """Custom table widget for displaying and managing data"""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.sorted_column = None  # Track which column is currently sorted
        self.sort_order = None
        self.init_table()
        self._install_column_delegates()

    def init_table(self):
        """Initialize the table widget with settings and styling"""
        # Set column count and headers
        self.setColumnCount(len(self.manager.get_column_names()))
        self.setHorizontalHeaderLabels(self.manager.get_column_names())

        # Apply styling
        self.setStyleSheet(TABLE_STYLE + """
            QTableWidget::item:focus {
                outline: none;
                border: none;
            }
        """)

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
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)

        # Horizontal header polish
        h_header = self.horizontalHeader()
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        h_header.setMinimumSectionSize(100)  # Minimum width per column
        h_header.setHighlightSections(False)
        h_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
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

    def add_row(self, data):
        """Add a row to the table"""
        row_position = self.rowCount()
        self.insertRow(row_position)

        for column, value in enumerate(data):
            item = QTableWidgetItem(str(value) if value is not None else "")
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.setItem(row_position, column, item)

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
            selected_row_data = [self.item(selected_row, col).text() for col in range(self.columnCount())]

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
                row_data = [self.item(row, col).text() for col in range(self.columnCount())]
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

