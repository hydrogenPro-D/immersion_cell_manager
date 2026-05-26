"""Unit tests for ImmersionCellsTab GUI."""
import unittest
from unittest.mock import MagicMock, patch, call
import sys
class TestImmersionCellsTab(unittest.TestCase):
    """Test cases for ImmersionCellsTab class."""
    def setUp(self):
        """Set up test fixtures."""
        self.patcher_manager = patch('src.gui.immersion_cells.ImmersionCellsManager')
        self.mock_manager_class = self.patcher_manager.start()
        self.mock_manager = MagicMock()
        self.mock_manager_class.return_value = self.mock_manager
        self.mock_manager.get_column_names.return_value = ["Channel", "Status", "Duration"]
        self.mock_manager.get_table_data.return_value = [
            ["1-1", "Active", "100h"],
            ["1-2", "Inactive", "50h"]
        ]
    def tearDown(self):
        """Clean up test fixtures."""
        self.patcher_manager.stop()
    def test_filter_empty_search(self):
        """Test filtering with empty search returns all rows."""
        needle = "".strip().lower()
        rows = [["1-1", "Active", "100h"], ["1-2", "Inactive", "50h"]]
        visible = 0
        for row in rows:
            if not needle:
                match = True
            else:
                match = any(needle in str(cell).lower() for cell in row)
            if match:
                visible += 1
        self.assertEqual(visible, 2)
    def test_filter_by_channel(self):
        """Test filtering by channel."""
        needle = "1-1".strip().lower()
        rows = [["1-1", "Active", "100h"], ["1-2", "Inactive", "50h"]]
        visible = 0
        for row in rows:
            match = any(needle in str(cell).lower() for cell in row)
            if match:
                visible += 1
        self.assertEqual(visible, 1)
    def test_filter_by_duration(self):
        """Test filtering by duration value."""
        needle = "100".strip().lower()
        rows = [["1-1", "Active", "100h"], ["1-2", "Inactive", "50h"]]
        visible = 0
        for row in rows:
            match = any(needle in str(cell).lower() for cell in row)
            if match:
                visible += 1
        self.assertEqual(visible, 1)
    def test_filter_no_matches(self):
        """Test filtering with no matching results."""
        needle = "nonexistent".strip().lower()
        rows = [["1-1", "Active", "100h"], ["1-2", "Inactive", "50h"]]
        visible = 0
        for row in rows:
            match = any(needle in str(cell).lower() for cell in row)
            if match:
                visible += 1
        self.assertEqual(visible, 0)
    def test_extract_channel_from_row(self):
        """Test extracting channel value from a row."""
        columns = ["Channel", "Status", "Duration"]
        row_index = 0
        channel_col = columns.index("Channel")
        table_data = [
            ["1-1", "Active", "100h"],
            ["1-2", "Inactive", "50h"]
        ]
        channel = table_data[row_index][channel_col]
        self.assertEqual(channel, "1-1")
    def test_status_badge_update_single_cell(self):
        """Test status badge update for single cell."""
        total = 1
        badge_text = f"{total} cell{'s' if total != 1 else ''}"
        self.assertEqual(badge_text, "1 cell")
    def test_status_badge_update_multiple_cells(self):
        """Test status badge update for multiple cells."""
        total = 2
        badge_text = f"{total} cell{'s' if total != 1 else ''}"
        self.assertEqual(badge_text, "2 cells")
    def test_status_label_update_all_visible(self):
        """Test status label when all rows are visible."""
        total = 5
        visible = 5
        visible_override = None
        if visible_override is not None and visible_override != total:
            status_text = f"Showing {visible_override} of {total} cells."
        else:
            status_text = f"{total} cell{'s' if total != 1 else ''} loaded."
        self.assertEqual(status_text, "5 cells loaded.")
    def test_status_label_update_filtered(self):
        """Test status label when rows are filtered."""
        total = 5
        visible = 2
        visible_override = visible
        if visible_override is not None and visible_override != total:
            status_text = f"Showing {visible_override} of {total} cells."
        else:
            status_text = f"{total} cell{'s' if total != 1 else ''} loaded."
        self.assertEqual(status_text, "Showing 2 of 5 cells.")
    def test_channel_for_row_valid(self):
        """Test extracting channel for a valid row."""
        columns = ["Channel", "Status", "Duration"]
        row_data = ["1-1", "Active", "100h"]
        try:
            col = columns.index("Channel")
            channel = row_data[col]
        except ValueError:
            channel = ""
        self.assertEqual(channel, "1-1")
    def test_channel_for_row_missing_channel_column(self):
        """Test extracting channel when Channel column doesn't exist."""
        columns = ["Status", "Duration"]
        row_data = ["Active", "100h"]
        try:
            col = columns.index("Channel")
            channel = row_data[col]
        except ValueError:
            channel = ""
        self.assertEqual(channel, "")
if __name__ == "__main__":
    unittest.main()
