"""Data manager for handling CSV file I/O and data persistence."""

import csv
from pathlib import Path


class DataManager:
    """Manages reading and writing data to CSV files."""

    def __init__(self, file_path: str):
        """
        Initialize the data manager with a file path.

        Args:
            file_path: Path to the CSV file
        """
        self.file_path = Path(file_path)
        self.ensure_file_exists()

    def ensure_file_exists(self) -> None:
        """Ensure the data file exists."""
        if not self.file_path.exists():
            raise FileNotFoundError(f"Data file not found: {self.file_path}")

    def _read_rows(self) -> tuple[list[str], list[dict]]:
        """Read the CSV file and return (header, rows)."""
        try:
            with open(self.file_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                rows = [dict(row) for row in reader]
                return fieldnames, rows
        except (OSError, csv.Error) as e:
            raise ValueError(f"Error reading CSV file: {e}")

    def get_data_list(self) -> list:
        """
        Get the data rows from the CSV file.

        Returns:
            List of data entries (each as a dict keyed by column name)
        """
        _, rows = self._read_rows()
        return rows

    def update_data_list(self, data_list: list, modified_by: str = "") -> None:
        """
        Overwrite the CSV file with ``data_list``.

        Args:
            data_list: New list of data entries (list of dicts)
            modified_by: Unused, kept for API compatibility
        """
        fieldnames, _ = self._read_rows()

        # If the file was empty or fieldnames unavailable, derive them from data.
        if not fieldnames and data_list:
            fieldnames = list(data_list[0].keys())

        try:
            with open(self.file_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in data_list:
                    writer.writerow({key: row.get(key, "") for key in fieldnames})
        except OSError as e:
            raise IOError(f"Error writing to CSV file: {e}")
