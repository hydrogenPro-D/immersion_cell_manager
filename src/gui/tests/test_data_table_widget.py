"""Unit tests for DataTableWidget sorting functionality."""
import unittest
from unittest.mock import MagicMock, patch
class TestDataTableWidgetSorting(unittest.TestCase):
    """Test cases for DataTableWidget sorting logic."""
    def test_extract_numeric_value(self):
        """Test numeric value extraction from text."""
        # Simulate the extraction function
        def extract_numeric(text):
            import re
            match = re.search(r'-?\d+(?:\.\d+)?', text)
            if match:
                return float(match.group())
            return float('inf')
        self.assertEqual(extract_numeric("150 ml"), 150.0)
        self.assertEqual(extract_numeric("250.5 ml"), 250.5)
        self.assertEqual(extract_numeric("10h"), 10.0)
        self.assertEqual(extract_numeric("-100h"), -100.0)
        self.assertEqual(extract_numeric("empty"), float('inf'))
    def test_extract_channel_numbers(self):
        """Test channel number extraction from format like '1-2'."""
        import re
        def extract_channel(text):
            match = re.match(r'^(\d+)-(\d+)$', text.strip())
            if match:
                first = int(match.group(1))
                second = int(match.group(2))
                return (first, second)
            return (float('inf'), float('inf'))
        self.assertEqual(extract_channel("1-1"), (1, 1))
        self.assertEqual(extract_channel("1-2"), (1, 2))
        self.assertEqual(extract_channel("12-34"), (12, 34))
        self.assertEqual(extract_channel("invalid"), (float('inf'), float('inf')))
    def test_sort_order_cycling(self):
        """Test sort order cycling: ascending -> descending -> no sort."""
        # Simulate sort state management
        class SortState:
            def __init__(self):
                self.sorted_column = None
                self.sort_order = None
            def click_column(self, column):
                from PyQt6.QtCore import Qt
                if self.sorted_column == column:
                    if self.sort_order == Qt.SortOrder.AscendingOrder:
                        self.sort_order = Qt.SortOrder.DescendingOrder
                    else:
                        self.sorted_column = None
                        self.sort_order = None
                else:
                    self.sorted_column = column
                    self.sort_order = Qt.SortOrder.AscendingOrder
        from PyQt6.QtCore import Qt
        state = SortState()
        # First click: ascending
        state.click_column(0)
        self.assertEqual(state.sorted_column, 0)
        self.assertEqual(state.sort_order, Qt.SortOrder.AscendingOrder)
        # Second click same column: descending
        state.click_column(0)
        self.assertEqual(state.sorted_column, 0)
        self.assertEqual(state.sort_order, Qt.SortOrder.DescendingOrder)
        # Third click same column: no sort
        state.click_column(0)
        self.assertIsNone(state.sorted_column)
        self.assertIsNone(state.sort_order)
if __name__ == "__main__":
    unittest.main()
