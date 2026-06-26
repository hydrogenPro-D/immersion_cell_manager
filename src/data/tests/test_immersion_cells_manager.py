"""Unit tests for ImmersionCellsManager column configuration."""
import unittest

from src.data.immersion_cells_manager import ImmersionCellsManager


class TestImmersionCellsManager(unittest.TestCase):
    """Column-mapping tests (no database access required)."""

    def test_column_names(self):
        """Test getting column names."""
        column_names = list(ImmersionCellsManager.COLUMNS_MAPPING.keys())
        self.assertIn("Channel", column_names)
        self.assertIn("Status", column_names)
        self.assertIn("Duration", column_names)

    def test_column_keys(self):
        """Test getting column keys."""
        column_keys = list(ImmersionCellsManager.COLUMNS_MAPPING.values())
        self.assertIn("channel", column_keys)
        self.assertIn("status", column_keys)
        self.assertIn("duration", column_keys)

    def test_get_csv_key_for_column(self):
        """Test the display-name -> column-key mapping."""
        mapping = ImmersionCellsManager.COLUMNS_MAPPING
        self.assertEqual(mapping.get("Channel"), "channel")
        self.assertEqual(mapping.get("Status"), "status")
        self.assertEqual(mapping.get("Duration"), "duration")


if __name__ == "__main__":
    unittest.main()
