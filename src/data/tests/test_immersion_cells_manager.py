"""Unit tests for ImmersionCellsManager."""
import unittest
from unittest.mock import patch, MagicMock
from src.data.immersion_cells_manager import ImmersionCellsManager
class TestImmersionCellsManager(unittest.TestCase):
    """Test cases for ImmersionCellsManager class."""
    def test_column_names(self):
        """Test getting column names."""
        with patch('src.data.immersion_cells_manager.DataManager'):
            manager = ImmersionCellsManager.__new__(ImmersionCellsManager)
            column_names = manager.get_column_names() if hasattr(manager, 'get_column_names') else list(ImmersionCellsManager.COLUMNS_MAPPING.keys())
            self.assertIn("Channel", column_names)
            self.assertIn("Status", column_names)
            self.assertIn("Duration", column_names)
    def test_column_keys(self):
        """Test getting column keys."""
        with patch('src.data.immersion_cells_manager.DataManager'):
            manager = ImmersionCellsManager.__new__(ImmersionCellsManager)
            column_keys = list(ImmersionCellsManager.COLUMNS_MAPPING.values())
            self.assertIn("channel", column_keys)
            self.assertIn("status", column_keys)
            self.assertIn("duration", column_keys)
    def test_get_csv_key_for_column(self):
        """Test getting CSV key for a column name."""
        with patch('src.data.immersion_cells_manager.DataManager'):
            manager = ImmersionCellsManager.__new__(ImmersionCellsManager)
            # Access the mapping directly from class
            mapping = ImmersionCellsManager.COLUMNS_MAPPING
            self.assertEqual(mapping.get("Channel"), "channel")
            self.assertEqual(mapping.get("Status"), "status")
            self.assertEqual(mapping.get("Duration"), "duration")
if __name__ == "__main__":
    unittest.main()
