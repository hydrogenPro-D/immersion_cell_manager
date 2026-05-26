"""Unit tests for DataManager."""
import unittest
import tempfile
import csv
from pathlib import Path
from src.data.data_manager import DataManager
class TestDataManager(unittest.TestCase):
    """Test cases for DataManager class."""
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_file = Path(self.temp_dir.name) / "test_data.csv"
        with open(self.temp_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "name", "value"])
            writer.writeheader()
            writer.writerow({"id": "1", "name": "Item A", "value": "100"})
            writer.writerow({"id": "2", "name": "Item B", "value": "200"})
    def tearDown(self):
        """Clean up test fixtures."""
        self.temp_dir.cleanup()
    def test_init_with_existing_file(self):
        """Test initialization with an existing file."""
        manager = DataManager(str(self.temp_file))
        self.assertEqual(manager.file_path, self.temp_file)
    def test_init_with_missing_file(self):
        """Test initialization with a missing file raises FileNotFoundError."""
        missing_file = Path(self.temp_dir.name) / "nonexistent.csv"
        with self.assertRaises(FileNotFoundError):
            DataManager(str(missing_file))
    def test_get_data_list(self):
        """Test reading data from CSV file."""
        manager = DataManager(str(self.temp_file))
        data = manager.get_data_list()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["id"], "1")
        self.assertEqual(data[0]["name"], "Item A")
    def test_update_data_list(self):
        """Test writing data to CSV file."""
        manager = DataManager(str(self.temp_file))
        new_data = [
            {"id": "1", "name": "Updated A", "value": "150"},
            {"id": "3", "name": "Item C", "value": "300"}
        ]
        manager.update_data_list(new_data)
        updated_data = manager.get_data_list()
        self.assertEqual(len(updated_data), 2)
        self.assertEqual(updated_data[0]["name"], "Updated A")
if __name__ == "__main__":
    unittest.main()
