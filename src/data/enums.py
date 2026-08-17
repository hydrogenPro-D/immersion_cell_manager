"""Domain enums shared by managers and the UI."""

from enum import Enum


# value -> (background_hex, foreground_hex). Defined at module level so it
# doesn't collide with Enum's own member machinery.
_STATUS_COLORS: dict[str, tuple[str, str]] = {
    "Available":     ("#CDEFD6", "#1E6B3A"),
    "In use":        ("#CCE2F8", "#1E4E8C"),
    "In repair":     ("#E04134", "#FFFFFF"),
    "Test finished": ("#B7E4DE", "#0B5C5C"),
}

# States that describe the physical cell, not an experiment/episode. History
# episodes can't be set to these (they belong to the cell, not the test).
_CELL_ONLY_STATUSES = {"Available", "In repair"}


class CellStatus(str, Enum):
    """Lifecycle states for an immersion cell.

    Each value also has an associated colour pair (background + text) intended
    to be rendered as a small rounded "pill" badge wherever the status is
    shown, see :meth:`color_for`.
    """

    AVAILABLE = "Available"
    IN_USE = "In use"
    IN_REPAIR = "In repair"
    TEST_FINISHED = "Test finished"

    @classmethod
    def values(cls) -> list[str]:
        """Return the human-readable values in declaration order."""
        return [member.value for member in cls]

    @classmethod
    def experiment_values(cls) -> list[str]:
        """Statuses valid for a history episode (excludes cell-only states)."""
        return [v for v in cls.values() if v not in _CELL_ONLY_STATUSES]

    @classmethod
    def color_for(cls, value: str) -> tuple[str, str]:
        """Return ``(background_hex, foreground_hex)`` for ``value``.

        Unknown values fall back to a neutral grey pill so legacy data is
        still rendered consistently.
        """
        return _STATUS_COLORS.get(value, ("#E2EAEF", "#4A5A66"))
