"""Dialog to administer the configurable list of projects.

Master–detail layout: the projects list is on the left; clicking a project shows
its details (name, color, description, density, Fe) on the right, editable in
place. Changes are saved with the detail panel's **Save** button. "Add project"
puts the panel into a blank state where Save creates a new project. Persistence
goes through the provided :class:`ProjectsManager`.

"Archive" hides a project from the assignment dropdowns without touching the
channels/history that already use it; archived projects sit in a separate list
below and can be restored. Nothing is ever hard-deleted from the UI.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QWidget,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QGraphicsDropShadowEffect,
    QMessageBox,
    QColorDialog,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QPixmap, QIcon

from src.gui.styles.dialog_styles import DIALOG_STYLE
from src.data.projects_manager import DEFAULT_PROJECT_COLOR, COLOR_PALETTE


# Extra styling layered on top of DIALOG_STYLE to give the projects list a
# darker, more obvious highlight when a project is selected.
_PROJECTS_LIST_STYLE = """
    QListWidget#ProjectsList {
        background-color: #FFFFFF;
        border: 1px solid #D8E2E8;
        border-radius: 8px;
        padding: 4px;
        outline: 0;
    }
    QListWidget#ProjectsList::item {
        padding: 8px 10px;
        border-radius: 6px;
        color: #1F2A33;
    }
    QListWidget#ProjectsList::item:hover {
        background-color: #EAF4F4;
    }
    QListWidget#ProjectsList::item:selected {
        background-color: #2F8B8B;
        color: #FFFFFF;
    }
"""


def _swatch(hex_color: str, size: int = 16) -> QIcon:
    """Return a small square color icon for ``hex_color``."""
    pix = QPixmap(QSize(size, size))
    pix.fill(QColor(hex_color))
    return QIcon(pix)


class ProjectsAdminDialog(QDialog):
    """Add/edit/remove projects with a list + inline detail panel."""

    def __init__(self, projects_manager, parent=None, on_remove=None,
                 on_rename=None):
        super().__init__(parent)
        self.projects_manager = projects_manager
        self._remove_callback = on_remove
        self._rename_callback = on_rename
        # Name of the project currently loaded in the detail panel; None means
        # the panel is in "new project" mode (Save creates it).
        self._current_name = None
        self._showing_archived = False  # which list the panel currently shows
        self.color = DEFAULT_PROJECT_COLOR
        self._original = ()      # snapshot of the loaded values (for change check)
        self._loading = False    # suppress the change check while populating
        self.init_ui()
        self._reload()

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        self.setWindowTitle("Manage Projects")
        self.setModal(True)
        self.resize(810, 500)

        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(DIALOG_STYLE + _PROJECTS_LIST_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("DialogCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.addWidget(self._build_header())
        card_layout.addWidget(self._build_body(), 1)
        outer.addWidget(card)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(20, 50, 70, 90))
        card.setGraphicsEffect(shadow)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("DialogHeader")
        header.setFixedHeight(80)

        layout = QVBoxLayout(header)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(2)

        title = QLabel("Manage Projects")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("Select a project to view and edit its details.")
        subtitle.setObjectName("DialogSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        return header

    def _build_body(self) -> QFrame:
        body = QFrame()
        body.setObjectName("DialogBody")

        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(24, 22, 24, 20)
        body_layout.setSpacing(18)

        body_layout.addWidget(self._build_left(), 0)
        body_layout.addWidget(self._build_right(), 1)
        return body

    def _build_left(self) -> QWidget:
        left = QWidget()
        left.setFixedWidth(250)
        layout = QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # One list, toggled between active and archived projects.
        self.toggle_btn = QPushButton("Show archived projects")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setAutoDefault(False)
        self.toggle_btn.clicked.connect(self._toggle_view)
        layout.addWidget(self.toggle_btn)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("ProjectsList")
        # Drag to reorder within the session; not persisted (restart = A–Z).
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_widget.currentItemChanged.connect(self._on_selection)
        layout.addWidget(self.list_widget, 1)

        # Stacked so they always fit the narrow sidebar (the shared button style
        # has a wide min-width that overflows two side by side). Add/Archive show
        # in the active view; Restore replaces them in the archived view.
        btn_col = QVBoxLayout()
        btn_col.setSpacing(8)
        self.add_btn = QPushButton("Add project")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setAutoDefault(False)
        self.add_btn.clicked.connect(self._on_add)
        self.archive_btn = QPushButton("Archive Project")
        self.archive_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.archive_btn.setAutoDefault(False)
        self.archive_btn.setEnabled(False)  # needs a selected project
        self.archive_btn.clicked.connect(self._on_archive)
        self.restore_btn = QPushButton("Restore")
        self.restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restore_btn.setAutoDefault(False)
        self.restore_btn.setVisible(False)
        self.restore_btn.clicked.connect(self._on_restore)
        btn_col.addWidget(self.add_btn)
        btn_col.addWidget(self.archive_btn)
        btn_col.addWidget(self.restore_btn)
        layout.addLayout(btn_col)
        return left

    def _build_right(self) -> QWidget:
        right = QWidget()
        layout = QVBoxLayout(right)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        name_label = QLabel("PROJECT NAME")
        name_label.setObjectName("FieldLabel")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Project name…")
        self.name_input.returnPressed.connect(self._on_save)
        layout.addWidget(name_label)
        layout.addWidget(self.name_input)

        color_label = QLabel("COLOR")
        color_label.setObjectName("FieldLabel")
        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        self.color_btn = QPushButton()
        self.color_btn.setToolTip("Pick the project color")
        self.color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color_btn.setFixedWidth(46)
        self.color_btn.setAutoDefault(False)
        self.color_btn.clicked.connect(self._on_pick_color)
        self.color_hint = QLabel(self.color)
        self.color_hint.setStyleSheet("color: #4A5A66; font-size: 12px;")
        color_row.addWidget(self.color_btn)
        color_row.addWidget(self.color_hint, 1)
        layout.addWidget(color_label)
        layout.addLayout(color_row)

        description_label = QLabel("DESCRIPTION (OPTIONAL)")
        description_label.setObjectName("FieldLabel")
        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText("Add a description…")
        self.description_input.setMinimumHeight(90)
        self.description_input.setTabChangesFocus(True)
        layout.addWidget(description_label)
        layout.addWidget(self.description_input, 1)

        specs_label = QLabel("Density and iron used in the project")
        specs_label.setObjectName("FieldLabel")
        layout.addWidget(specs_label)
        specs_row = QHBoxLayout()
        specs_row.setSpacing(10)
        density_col = QVBoxLayout()
        density_col.setSpacing(4)
        d_lbl = QLabel("Density (rho)")
        d_lbl.setObjectName("FieldLabel")
        self.density_input = QLineEdit()
        self.density_input.setPlaceholderText("e.g. 1282")
        density_col.addWidget(d_lbl)
        density_col.addWidget(self.density_input)
        fe_col = QVBoxLayout()
        fe_col.setSpacing(4)
        f_lbl = QLabel("Fe [ppm]")
        f_lbl.setObjectName("FieldLabel")
        self.fe_ppm_input = QLineEdit()
        self.fe_ppm_input.setPlaceholderText("e.g. 1.3")
        fe_col.addWidget(f_lbl)
        fe_col.addWidget(self.fe_ppm_input)
        specs_row.addLayout(density_col)
        specs_row.addLayout(fe_col)
        layout.addLayout(specs_row)

        # Enable Save only when something actually changed.
        for w in (self.name_input, self.density_input, self.fe_ppm_input):
            w.textChanged.connect(self._update_save_state)
        self.description_input.textChanged.connect(self._update_save_state)

        footer = QHBoxLayout()
        self.save_btn = QPushButton("Save changes")
        self.save_btn.setDefault(True)
        self.save_btn.setEnabled(False)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self._on_save)
        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setAutoDefault(False)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(self.save_btn)
        footer.addStretch(1)
        footer.addWidget(close_btn)
        layout.addLayout(footer)
        return right

    # --------------------------------------------------------------- Colors
    def _update_color_button(self) -> None:
        self.color_btn.setStyleSheet(
            f"background: {self.color}; border: 1px solid #D8E2E8;"
            " border-radius: 8px; min-width: 0px; padding: 9px 0px;"
        )

    def _on_pick_color(self) -> None:
        color = QColorDialog.getColor(
            QColor(self.color), self, "Choose project color"
        )
        if color.isValid():
            self.color = color.name()
            self._update_color_button()
            self.color_hint.setText(self.color)
            self._update_save_state()

    # ----------------------------------------------------------------- Data
    def _toggle_view(self) -> None:
        """Flip the list between active and archived projects."""
        self._showing_archived = not self._showing_archived
        archived = self._showing_archived
        self.toggle_btn.setText(
            "Show active projects" if archived else "Show archived projects"
        )
        self.add_btn.setVisible(not archived)
        self.archive_btn.setVisible(not archived)
        self.restore_btn.setVisible(archived)
        # Reordering is only meaningful for the active list.
        self.list_widget.setDragDropMode(
            QListWidget.DragDropMode.NoDragDrop if archived
            else QListWidget.DragDropMode.InternalMove
        )
        self._reload()

    def _reload(self, select_name: str | None = None) -> None:
        """Repopulate the list (active or archived) and select a row."""
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        colors = self.projects_manager.get_project_colors()
        names = (self.projects_manager.get_archived_projects()
                 if self._showing_archived
                 else self.projects_manager.get_projects())
        projects = sorted(names, key=str.casefold)
        target = -1
        for i, project in enumerate(projects):
            item = QListWidgetItem(
                _swatch(colors.get(project, DEFAULT_PROJECT_COLOR)), project
            )
            self.list_widget.addItem(item)
            if project == select_name:
                target = i
        self.list_widget.blockSignals(False)

        if target < 0 and select_name is None and projects:
            target = 0
        if target >= 0:
            self.list_widget.setCurrentRow(target)  # fires _on_selection -> load
        else:
            self.restore_btn.setEnabled(False)
            self.archive_btn.setEnabled(False)
            self._clear_form()

    def _on_selection(self, current, _previous) -> None:
        if self._showing_archived:
            self.restore_btn.setEnabled(current is not None)
        else:
            self.archive_btn.setEnabled(current is not None)
        if current is not None:
            self._load_form(current.text())

    def _load_form(self, name: str) -> None:
        self._loading = True
        self._current_name = name
        self.name_input.setText(name)
        self.color = self.projects_manager.get_color(name) or DEFAULT_PROJECT_COLOR
        self._update_color_button()
        self.color_hint.setText(self.color)
        self.description_input.setPlainText(
            self.projects_manager.get_description(name)
        )
        self.density_input.setText(self.projects_manager.get_density(name))
        self.fe_ppm_input.setText(self.projects_manager.get_fe_ppm(name))
        self._loading = False
        self._original = self._snapshot()
        # Archived projects are shown read-only (restore to edit them).
        self._set_editable(not self._showing_archived)
        self._update_save_state()

    def _clear_form(self) -> None:
        """Blank detail panel for a new (unsaved) project."""
        self._loading = True
        self._current_name = None
        self.name_input.clear()
        self.color = COLOR_PALETTE[0] if COLOR_PALETTE else DEFAULT_PROJECT_COLOR
        self._update_color_button()
        self.color_hint.setText(self.color)
        self.description_input.clear()
        self.density_input.clear()
        self.fe_ppm_input.clear()
        self._loading = False
        self._original = self._snapshot()
        self._set_editable(not self._showing_archived)
        self._update_save_state()

    def _set_editable(self, editable: bool) -> None:
        """Toggle the detail form between editable and read-only (archived view)."""
        self.name_input.setReadOnly(not editable)
        self.description_input.setReadOnly(not editable)
        self.density_input.setReadOnly(not editable)
        self.fe_ppm_input.setReadOnly(not editable)
        self.color_btn.setEnabled(editable)
        self.save_btn.setVisible(editable)

    def _snapshot(self) -> tuple:
        """Current form values (compared against ``_original`` to detect edits)."""
        return (
            self.name_input.text().strip(),
            self.color,
            self.description_input.toPlainText().strip(),
            self.density_input.text().strip(),
            self.fe_ppm_input.text().strip(),
        )

    def _update_save_state(self) -> None:
        if self._loading:
            return
        changed = self._snapshot() != self._original
        has_name = bool(self.name_input.text().strip())
        self.save_btn.setEnabled(changed and has_name)

    # -------------------------------------------------------------- Actions
    def _on_add(self) -> None:
        self.list_widget.blockSignals(True)
        self.list_widget.setCurrentItem(None)
        self.list_widget.blockSignals(False)
        self.archive_btn.setEnabled(False)  # nothing selected to archive
        self._clear_form()
        self.name_input.setFocus()

    def _on_save(self) -> None:
        if not self.save_btn.isEnabled():  # nothing changed (e.g. Enter key)
            return
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.information(
                self, "Name required", "Please enter a project name."
            )
            return
        description = self.description_input.toPlainText().strip()
        density = self.density_input.text().strip()
        fe_ppm = self.fe_ppm_input.text().strip()

        if self._current_name is None:
            # New project.
            if not self.projects_manager.add_project(
                name, self.color, description, density, fe_ppm
            ):
                if name in set(self.projects_manager.get_archived_projects()):
                    QMessageBox.information(
                        self, "Project archived",
                        f"'{name}' already exists but is archived. Select it in "
                        "the Archived list and click Restore to bring it back.",
                    )
                else:
                    QMessageBox.information(
                        self, "Project exists", f"'{name}' already exists."
                    )
                return
            self._reload(select_name=name)
            return

        # Existing project (possibly renamed).
        old_name = self._current_name
        if name != old_name and name in set(self.projects_manager.get_projects()):
            QMessageBox.information(
                self, "Project exists", f"'{name}' already exists."
            )
            return
        if not self.projects_manager.rename_project(old_name, name, self.color):
            QMessageBox.warning(
                self, "Update failed", f"Could not update '{old_name}'."
            )
            return
        self.projects_manager.set_project_description(name, description)
        self.projects_manager.set_project_specs(name, density, fe_ppm)
        if name != old_name and self._rename_callback is not None:
            self._rename_callback(old_name, name)
        self._reload(select_name=name)

    def _on_archive(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(
                self, "No selection", "Select a project to archive."
            )
            return
        name = item.text()
        confirm = QMessageBox.question(
            self,
            "Archive project",
            f"Archive project '{name}'?\n\nIt stays on the channels and station-"
            "summary entries that already use it, but can no longer be assigned "
            "to new channels. You can restore it later.",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            if not self.projects_manager.archive_project(name):
                QMessageBox.warning(
                    self, "Archive failed", f"Could not archive '{name}'."
                )
                return
            if self._remove_callback is not None:
                self._remove_callback(name)  # refresh the app's project combos
            self._reload()

    def _on_restore(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(
                self, "No selection", "Select an archived project to restore."
            )
            return
        name = item.text()
        if not self.projects_manager.restore_project(name):
            QMessageBox.warning(
                self, "Restore failed", f"Could not restore '{name}'."
            )
            return
        if self._remove_callback is not None:
            self._remove_callback(name)  # refresh the app's project combos
        # Still in the archived view: the restored project drops out of the list.
        self._reload()

    # ---------------------------------------------------- Window dragging
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(
            self, "_drag_pos"
        ):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        super().mouseMoveEvent(event)
