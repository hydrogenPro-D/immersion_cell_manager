"""Manager for immersion cells data and configuration."""

from pathlib import Path
from src.data.data_manager import DataManager
from src.data.enums import CellStatus
from src.gui.widgets.field_types import FieldSpec, FieldType


class ImmersionCellsManager:
    """Manages immersion cells data and column configuration."""

    # Mapping of display names to CSV column keys
    COLUMNS_MAPPING = {
        "Channel": "channel",
        "SuperUser": "super_user",
        "Current owner": "current_owner",
        "Assembled by": "assembled_by",
        "Status": "status",
        "Start date": "start_date",
        "Duration": "duration",
        "Cathode": "cathode",
        "Anode": "anode",
        "Separator": "separator",
        "Data filename": "data_filename",
        "Added water by timing": "added_water_b",
        "Comments": "comments"
    }

    # Per-column editor behaviour. Columns not listed default to plain text.
    # ``Channel`` is locked because it is the row identifier.
    FIELD_SPECS = {
        "Channel": FieldSpec(name="Channel", field_type=FieldType.TEXT, read_only=True),
        "Status": FieldSpec(
            name="Status",
            field_type=FieldType.CHOICE,
            choices=CellStatus.values(),
            color_resolver=CellStatus.color_for,
        ),
        "Start date": FieldSpec(
            name="Start date",
            field_type=FieldType.DATE,
        ),
    }

    def __init__(self):
        """Initialize the immersion cells manager with data file path."""
        # Get the path to the CSV file
        current_dir = Path(__file__).parent
        csv_file = current_dir / "csv" / "immersion_cells.csv"
        self.data_manager = DataManager(str(csv_file))

    def get_column_names(self) -> list:
        """
        Get the list of column names for the table.

        Returns:
            List of column names (display names)
        """
        return list(self.COLUMNS_MAPPING.keys())

    def get_field_spec(self, column_name: str) -> FieldSpec:
        """Return the :class:`FieldSpec` for ``column_name``.

        Columns without an explicit spec default to a plain text field.
        """
        return self.FIELD_SPECS.get(
            column_name, FieldSpec(name=column_name, field_type=FieldType.TEXT)
        )

    def get_field_specs(self) -> list[FieldSpec]:
        """Return field specs in column order."""
        return [self.get_field_spec(name) for name in self.get_column_names()]

    def get_column_keys(self) -> list:
        """
        Get the list of CSV column keys corresponding to columns.

        Returns:
            List of CSV column keys
        """
        return list(self.COLUMNS_MAPPING.values())

    def get_csv_key_for_column(self, column_name: str) -> str:
        """
        Get the CSV column key for a given column display name.

        Args:
            column_name: Display name of the column

        Returns:
            CSV column key
        """
        return self.COLUMNS_MAPPING.get(column_name, "")

    def get_column_name_for_key(self, csv_key: str) -> str:
        """
        Get the column display name for a given CSV column key.

        Args:
            csv_key: CSV column key

        Returns:
            Display name of the column
        """
        for col_name, key in self.COLUMNS_MAPPING.items():
            if key == csv_key:
                return col_name
        return ""

    def load_all_cells(self) -> list:
        """
        Load all immersion cells from the CSV file.

        Returns:
            List of immersion cell dictionaries
        """
        return self.data_manager.get_data_list()

    def get_table_data(self) -> list:
        """
        Get immersion cells data formatted for table display.

        Returns:
            List of lists, where each inner list is a row
        """
        cells = self.load_all_cells()
        table_data = []

        for cell in cells:
            row = []
            for csv_key in self.get_column_keys():
                row.append(cell.get(csv_key, ""))
            table_data.append(row)

        return table_data

    def save_table_data(self, table_data: list, modified_by: str = "") -> None:
        """
        Save table data back to the CSV file.

        Args:
            table_data: List of lists representing table rows
            modified_by: Name/email of the user making the change
        """
        cells = []

        for row in table_data:
            cell = {}
            for i, csv_key in enumerate(self.get_column_keys()):
                if i < len(row):
                    cell[csv_key] = row[i]
            cells.append(cell)

        self.data_manager.update_data_list(cells, modified_by)

    def get_cell_by_channel(self, channel: str) -> dict:
        """
        Get a specific immersion cell by its channel ID.

        Args:
            channel: Channel identifier (e.g., "1-1")

        Returns:
            Cell dictionary or empty dict if not found
        """
        cells = self.load_all_cells()
        for cell in cells:
            if cell.get("channel") == channel:
                return cell
        return {}

    def update_row_by_channel(self, row_data: list) -> None:
        """
        Update a row in the CSV file by matching its channel ID.

        This method extracts the channel ID from the row data, finds the matching
        record in the CSV file, and updates it with the new values.

        Args:
            row_data: List of values corresponding to columns in column order
        """
        # Get the channel column index
        try:
            channel_col = self.get_column_names().index("Channel")
        except ValueError:
            raise ValueError("Channel column not found in column mapping")

        # Extract the channel ID from the row data
        if channel_col >= len(row_data):
            raise ValueError("Row data is shorter than expected")

        channel = row_data[channel_col]
        if not channel:
            raise ValueError("Channel ID cannot be empty")

        # Load all cells
        cells = self.load_all_cells()

        # Find and update the matching cell
        updated = False
        for i, cell in enumerate(cells):
            if cell.get("channel") == channel:
                # Update this cell with new data
                for col_idx, csv_key in enumerate(self.get_column_keys()):
                    if col_idx < len(row_data):
                        cells[i][csv_key] = row_data[col_idx]
                updated = True
                break

        if not updated:
            raise ValueError(f"Cell with channel '{channel}' not found")

        # Save the updated cells
        self.data_manager.update_data_list(cells)

    def add_new_row(self, row_data: list) -> None:
        """
        Add a new row to the CSV file.

        This method creates a new cell record from the row data and appends it
        to the CSV file.

        Args:
            row_data: List of values corresponding to columns in column order
        """
        # Load all existing cells
        cells = self.load_all_cells()

        # Create new cell from row data
        new_cell = {}
        for col_idx, csv_key in enumerate(self.get_column_keys()):
            if col_idx < len(row_data):
                new_cell[csv_key] = row_data[col_idx]

        # Append new cell
        cells.append(new_cell)

        # Save updated cells
        self.data_manager.update_data_list(cells)

    def delete_row_by_channel(self, channel: str) -> None:
        """
        Delete a row from the CSV file by matching its channel ID.

        Args:
            channel: Channel identifier to delete

        Raises:
            ValueError: If channel is empty or cell not found
        """
        if not channel:
            raise ValueError("Channel ID cannot be empty")

        # Load all cells
        cells = self.load_all_cells()

        # Find and remove the matching cell
        initial_count = len(cells)
        cells = [cell for cell in cells if cell.get("channel") != channel]

        if len(cells) == initial_count:
            raise ValueError(f"Cell with channel '{channel}' not found")

        # Save the updated cells
        self.data_manager.update_data_list(cells)

