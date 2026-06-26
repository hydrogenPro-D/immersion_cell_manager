"""Manager for the list of selectable projects, colors, and descriptions.

Backed by the ``icm.projects`` table: reads via ``SELECT``, writes via the
``icm.usp_project_*`` stored procedures. Each project has a color (used to paint
the Station Summary bars) and an optional description (shown as a tooltip).
"""

from src.data.db import get_db, DatabaseError, to_text

# Color used when a project has no explicit color (or for legacy rows).
DEFAULT_PROJECT_COLOR = "#3FA3A3"

# Neutral color used for episodes that have no project assigned.
NO_PROJECT_COLOR = "#C7D3DB"

# Palette cycled through when a project is added without an explicit color.
COLOR_PALETTE = [
    "#3FA3A3", "#E0734D", "#7E57C2", "#43A047", "#F4B400",
    "#1E88E5", "#D81B60", "#8D6E63", "#00897B", "#5E35B1",
]

# Process-wide cache of the projects rows, shared by every ProjectsManager
# instance. The project list is tiny and changes rarely, but it is read on
# *every* pill repaint and table mouse-move, so without this each of those
# events would fire a SELECT round-trip to the database. The cache is cleared
# on any local write (below) and by the GUI when the change poller detects an
# external change, so it never serves stale colors for long.
_rows_cache: list[tuple[str, str, str]] | None = None


def invalidate_projects_cache() -> None:
    """Drop the cached project list so the next read re-queries the DB."""
    global _rows_cache
    _rows_cache = None


class ProjectsManager:
    """Reads/writes the list of projects + colors + descriptions in the DB."""

    def __init__(self, db=None):
        self._db = db or get_db()

    # ------------------------------------------------------------------ IO
    def _rows(self) -> list[tuple[str, str, str]]:
        """Return ``[(name, color, description), ...]`` in insertion order."""
        global _rows_cache
        if _rows_cache is not None:
            return _rows_cache
        records = self._db.fetch_all(
            "SELECT project_id, color, description FROM icm.projects ORDER BY id"
        )
        rows: list[tuple[str, str, str]] = []
        for i, r in enumerate(records):
            name = to_text(r.get("project_id")).strip()
            if not name:
                continue
            color = to_text(r.get("color")).strip() or COLOR_PALETTE[i % len(COLOR_PALETTE)]
            description = to_text(r.get("description")).strip()
            rows.append((name, color, description))
        _rows_cache = rows
        return rows

    # ----------------------------------------------------------- Public API
    def get_projects(self) -> list[str]:
        """Return the list of project names (in insertion order)."""
        return [name for name, _, _ in self._rows()]

    def get_project_colors(self) -> dict[str, str]:
        """Return a mapping of ``{project_name: color_hex}``."""
        return {name: color for name, color, _ in self._rows()}

    def get_project_descriptions(self) -> dict[str, str]:
        """Return a mapping of ``{project_name: description}``."""
        return {name: description for name, _, description in self._rows()}

    def get_description(self, name: str) -> str:
        """Return the description for ``name`` (or empty string if unknown)."""
        name = (name or "").strip()
        return self.get_project_descriptions().get(name, "")

    def get_color(self, name: str) -> str:
        """Return the color for ``name`` (or the default if unknown)."""
        name = (name or "").strip()
        return self.get_project_colors().get(name, DEFAULT_PROJECT_COLOR)

    def color_for(self, name: str) -> tuple[str, str]:
        """Return ``(background, foreground)`` colors for a project name.

        Empty / unknown projects get a neutral background.
        """
        name = (name or "").strip()
        bg = self.get_project_colors().get(name) or NO_PROJECT_COLOR
        return bg, self.foreground_for(bg)

    def add_project(self, name: str, color: str | None = None,
                    description: str | None = None) -> bool:
        """Add a project. Returns ``False`` if invalid or it already exists."""
        name = (name or "").strip()
        if not name:
            return False
        if not color:
            color = COLOR_PALETTE[len(self._rows()) % len(COLOR_PALETTE)]
        description = (description or "").strip()
        try:
            self._db.exec_proc("usp_project_insert", {
                "project_id": name, "color": color, "description": description,
            })
            invalidate_projects_cache()
            return True
        except DatabaseError:
            return False  # most likely the UNIQUE name already exists

    def set_project_color(self, name: str, color: str) -> bool:
        """Update the color of an existing project. Returns False if missing."""
        name = (name or "").strip()
        color = (color or "").strip()
        if not name or not color:
            return False
        try:
            # description=None -> usp_project_update keeps the existing one.
            self._db.exec_proc("usp_project_update", {
                "project_id": name, "color": color, "description": None,
            })
            invalidate_projects_cache()
            return True
        except DatabaseError:
            return False

    def set_project_description(self, name: str, description: str) -> bool:
        """Update the description of an existing project. Returns False if missing."""
        name = (name or "").strip()
        if not name:
            return False
        try:
            self._db.exec_proc("usp_project_update", {
                "project_id": name, "color": None,
                "description": (description or "").strip(),
            })
            invalidate_projects_cache()
            return True
        except DatabaseError:
            return False

    def rename_project(self, old_name: str, new_name: str,
                       color: str | None = None) -> bool:
        """Rename a project (and optionally recolor it).

        The DB FK ``ON UPDATE CASCADE`` propagates the new name to every cell
        and history row automatically. Returns ``False`` on missing/collision.
        """
        old_name = (old_name or "").strip()
        new_name = (new_name or "").strip()
        if not old_name or not new_name:
            return False
        if new_name != old_name and new_name in set(self.get_projects()):
            return False
        try:
            self._db.exec_proc("usp_project_rename", {
                "old_project_id": old_name, "new_project_id": new_name,
                "color": (color or None),
            })
            invalidate_projects_cache()
            return True
        except DatabaseError:
            return False

    def remove_project(self, name: str) -> bool:
        """Remove a project. Returns False if it wasn't present.

        The DB FK ``ON DELETE SET NULL`` clears the reference on every cell and
        history row automatically.
        """
        name = (name or "").strip()
        if not name:
            return False
        try:
            self._db.exec_proc("usp_project_delete", {"project_id": name})
            invalidate_projects_cache()
            return True
        except DatabaseError:
            return False

    # -------------------------------------------------------------- Helpers
    @staticmethod
    def foreground_for(bg_hex: str) -> str:
        """Pick a readable text color (light or dark) for a background hex."""
        try:
            h = (bg_hex or "").lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except (ValueError, IndexError):
            return "#0B3B3B"
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "#FFFFFF" if luminance < 0.6 else "#0B3B3B"
