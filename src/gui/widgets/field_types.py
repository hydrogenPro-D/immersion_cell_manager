"""Declarative descriptions of editable fields used by EditRowDialog."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class FieldType(Enum):
    """How a column should be rendered inside the edit dialog."""

    TEXT = "text"
    DATE = "date"          # ISO yyyy-MM-dd (with an hours picker)
    DATE_ONLY = "date_only"  # ISO yyyy-MM-dd, optional (can be left blank)
    CHOICE = "choice"      # one-of from FieldSpec.choices


# Returns (background_hex, foreground_hex) for a given value.
ColorResolver = Callable[[str], tuple[str, str]]


@dataclass(frozen=True)
class FieldSpec:
    """Describes how a single column is edited.

    Attributes
    ----------
    name : str
        Display name shown in the dialog label (and as the table column).
    field_type : FieldType
        Which editor widget to render.
    choices : list[str]
        Allowed values when ``field_type == FieldType.CHOICE``.
    read_only : bool
        If True the field is shown but not editable.
    placeholder : str
        Optional placeholder text for TEXT fields.
    date_format : str
        Qt date format string for DATE fields. ISO by default.
    color_resolver : Optional[ColorResolver]
        If set, CHOICE fields render values as colored pill badges. The
        resolver maps a value to ``(background_hex, foreground_hex)``.
    """

    name: str
    field_type: FieldType = FieldType.TEXT
    choices: list[str] = field(default_factory=list)
    read_only: bool = False
    placeholder: str = ""
    date_format: str = "yyyy-MM-dd"
    color_resolver: Optional[ColorResolver] = None


