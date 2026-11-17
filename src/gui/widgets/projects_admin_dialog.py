"""Dialog to administer the configurable list of projects.

Master-detail layout: the projects list is on the left; clicking a project shows
its details (name, owner, color, description, density, Fe) on the right, editable in
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
from src.gui.widgets.drag_move import DragMoveMixin
from src.gui.widgets.confirm_dialog import ConfirmDialog
from src.data.projects_manager import DEFAULT_PROJECT_COLOR, COLOR_PALETTE
from src.gui.widgets.project_history_dialog import ProjectHistoryDialog


# The description box: a full, visible outline (the shared style only hints at one).
_TEXT_BOX_STYLE = """
    QTextEdit {
        background: #FFFFFF;
        border: 1px solid #C7D3DB;
        border-radius: 6px;
        padding: 4px;
    }
    QTextEdit:focus {
        border: 1px solid #3FA3A3;
    }
"""

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
""" + _TEXT_BOX_STYLE + """
    QLineEdit[viewMode="true"], QTextEdit[viewMode="true"],
    QLineEdit[viewMode="true"]:hover, QLineEdit[viewMode="true"]:focus,
    QTextEdit[viewMode="true"]:hover, QTextEdit[viewMode="true"]:focus {
        background: transparent;
        border: none;
        padding-left: 0px;
        color: #1F2A33;
    }
"""


def _swatch(hex_color: str, size: int = 16) -> QIcon:
    """Return a small square color icon for ``hex_color``."""
    pix = QPixmap(QSize(size, size))
    pix.fill(QColor(hex_color))
    return QIcon(pix)


class ProjectsAdminDialog(DragMoveMixin, QDialog):
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
        self._reloading = False  # list rebuilt by code: no unsaved-changes question
        self._editing = False    # Edit project pressed (fields are inputs)
        self.init_ui()
        self._reload()

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        self.setWindowTitle("Manage Projects")
        self.setModal(True)
        self.resize(810, 580)

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
        # Drag to reorder within the session; not persisted (restart = A-Z).
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_widget.currentItemChanged.connect(self._on_selection)
        layout.addWidget(self.list_widget, 1)

        # Stacked so they always fit the narrow sidebar (the shared button style
        # has a wide min-width that overflows two side by side). Add/Archive show
        # in the active view; Restore replaces them in the archived view.
        btn_col = QVBoxLayout()
        btn_col.setSpacing(8)
        self.add_btn = QPushButton("Add new project")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setAutoDefault(False)
        self.add_btn.clicked.connect(self._on_add)
        self.archive_btn = QPushButton("Archive selected project")
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
        self.history_btn = QPushButton("Project history")
        self.history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_btn.setAutoDefault(False)
        self.history_btn.setEnabled(False)  # needs a selected project
        self.history_btn.clicked.connect(self._on_history)
        self.edit_btn = QPushButton("Edit project")
        self.edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_btn.setAutoDefault(False)
        self.edit_btn.setVisible(False)  # needs a selected, active project
        self.edit_btn.clicked.connect(self._on_edit)
        name_row = QHBoxLayout()
        name_row.addWidget(name_label, 0, Qt.AlignmentFlag.AlignBottom)
        name_row.addStretch(1)
        name_row.addWidget(self.edit_btn)
        name_row.addWidget(self.history_btn)
        layout.addLayout(name_row)
        layout.addWidget(self.name_input)

        owner_label = QLabel("PROJECT OWNER (OPTIONAL)")
        owner_label.setObjectName("FieldLabel")
        self.owner_input = QLineEdit()
        self.owner_input.returnPressed.connect(self._on_save)
        layout.addWidget(owner_label)
        layout.addWidget(self.owner_input)
        # Hidden until migration 025 adds the column (nowhere to save it).
        has_owner = self.projects_manager.has_owner_column()
        owner_label.setVisible(has_owner)
        self.owner_input.setVisible(has_owner)

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
        for w in (self.name_input, self.owner_input, self.density_input, self.fe_ppm_input):
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
        if not self._confirm_discard():
            return
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
            # Fires _on_selection -> load; callers already settled any unsaved edits.
            self._reloading = True
            try:
                self.list_widget.setCurrentRow(target)
            finally:
                self._reloading = False
        else:
            self.restore_btn.setEnabled(False)
            self.archive_btn.setEnabled(False)
            self.history_btn.setEnabled(False)
            self._clear_form()

    def _on_selection(self, current, previous) -> None:
        if not self._reloading and not self._confirm_discard():
            self.list_widget.blockSignals(True)  # Stay: back to the edited project
            self.list_widget.setCurrentItem(previous)
            self.list_widget.blockSignals(False)
            return
        self.history_btn.setEnabled(current is not None)
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
        self.owner_input.setText(self.projects_manager.get_owner(name))
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
        self._set_editable(False)  # shown, not editable, until "Edit project"
        self._update_save_state()

    def _clear_form(self) -> None:
        """Blank, read-only detail panel: no project selected (empty list)."""
        self._loading = True
        self._current_name = None
        self.name_input.clear()
        self.owner_input.clear()
        self.color = COLOR_PALETTE[0] if COLOR_PALETTE else DEFAULT_PROJECT_COLOR
        self._update_color_button()
        self.color_hint.setText(self.color)
        self.description_input.clear()
        self.density_input.clear()
        self.fe_ppm_input.clear()
        self._loading = False
        self._original = self._snapshot()
        self._set_editable(False)
        self._update_save_state()

    def _set_editable(self, editable: bool) -> None:
        """Edit mode (input fields, Save) or view mode (values shown as plain text).
        Archived projects only have view mode (restore to edit them)."""
        editable = editable and self._current_name is not None and not self._showing_archived
        self._editing = editable
        if not hasattr(self, "_edit_placeholders"):
            self._edit_placeholders = {w: w.placeholderText() for w in self._text_fields()}
        for w in self._text_fields():
            w.setReadOnly(not editable)
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus if editable else Qt.FocusPolicy.NoFocus)
            w.setPlaceholderText(self._edit_placeholders[w] if editable else "-")
            w.setProperty("viewMode", not editable)
            w.style().unpolish(w)  # re-apply the view / edit look
            w.style().polish(w)
        self.color_btn.setEnabled(editable)
        self.save_btn.setVisible(editable)
        self.edit_btn.setVisible(self._current_name is not None and not self._showing_archived)
        self.edit_btn.setText("Cancel editing" if editable else "Edit project")

    def _text_fields(self) -> tuple:
        return (self.name_input, self.owner_input, self.description_input,
                self.density_input, self.fe_ppm_input)

    def _on_edit(self) -> None:
        if not self._editing:
            self._set_editable(True)
            self.name_input.setFocus()
            self.name_input.end(False)
        elif self._confirm_discard():
            self._load_form(self._current_name)  # back to the stored values, view mode

    def _snapshot(self) -> tuple:
        """Current form values (compared against ``_original`` to detect edits)."""
        return (
            self.name_input.text().strip(),
            self.owner_input.text().strip(),
            self.color,
            self.description_input.toPlainText().strip(),
            self.density_input.text().strip(),
            self.fe_ppm_input.text().strip(),
        )

    def _has_unsaved_changes(self) -> bool:
        return (self._current_name is not None and not self._showing_archived
                and self._snapshot() != self._original)

    def _confirm_discard(self) -> bool:
        """True if there are no unsaved edits, or the user agrees to drop them."""
        return not self._has_unsaved_changes() or ConfirmDialog.ask(
            self, title="Unsaved changes",
            message=f"Leave without saving the changes to <b>{self._current_name}</b>?",
            confirm_text="Leave", cancel_text="Stay", destructive=True)

    def done(self, result: int) -> None:
        """Close (button or Esc): ask first while there are unsaved changes."""
        if self._confirm_discard():
            super().done(result)

    def _update_save_state(self) -> None:
        if self._loading:
            return
        changed = self._snapshot() != self._original
        has_name = bool(self.name_input.text().strip())
        self.save_btn.setEnabled(changed and has_name)

    # -------------------------------------------------------------- Actions
    def _on_add(self) -> None:
        if not self._confirm_discard():
            return
        dialog = NewProjectDialog(self.projects_manager, self)
        if dialog.exec() and dialog.created_name:
            self._reload(select_name=dialog.created_name)

    def _on_history(self) -> None:
        item = self.list_widget.currentItem()
        if item is not None:
            ProjectHistoryDialog(self, item.text()).exec()

    def _on_save(self) -> None:
        # New projects are made in NewProjectDialog; this saves the selected one.
        if not self.save_btn.isEnabled() or self._current_name is None:
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
        owner = self.owner_input.text().strip()

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
        if owner != self.projects_manager.get_owner(name):
            self.projects_manager.set_project_owner(name, owner)
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


class NewProjectDialog(QDialog):
    """A separate form for a new project; Create adds it. ``created_name`` is set
    once it exists."""

    def __init__(self, projects_manager, parent=None):
        super().__init__(parent)
        self.projects_manager = projects_manager
        self.created_name = None
        count = len(projects_manager.get_projects()) + len(projects_manager.get_archived_projects())
        self.color = COLOR_PALETTE[count % len(COLOR_PALETTE)]
        self.setWindowTitle("New project")
        self.setModal(True)
        self.resize(540, 0)
        self.setStyleSheet(DIALOG_STYLE + _TEXT_BOX_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(10)
        title = QLabel("New project")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#000000;")
        root.addWidget(title)

        def field(label: str, widget) -> None:
            lbl = QLabel(label)
            lbl.setObjectName("FieldLabel")
            root.addWidget(lbl)
            if isinstance(widget, QWidget):
                root.addWidget(widget)
            else:
                root.addLayout(widget)

        self.name_input = QLineEdit()
        field("PROJECT NAME", self.name_input)
        self.owner_input = QLineEdit()
        if projects_manager.has_owner_column():
            field("PROJECT OWNER (OPTIONAL)", self.owner_input)

        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        self.color_btn = QPushButton()
        self.color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color_btn.setFixedWidth(46)
        self.color_btn.setAutoDefault(False)
        self.color_btn.clicked.connect(self._pick_color)
        self.color_hint = QLabel()
        self.color_hint.setStyleSheet("color: #4A5A66; font-size: 12px;")
        color_row.addWidget(self.color_btn)
        color_row.addWidget(self.color_hint, 1)
        field("COLOR", color_row)
        self._show_color()

        self.description_input = QTextEdit()
        self.description_input.setFixedHeight(80)
        self.description_input.setTabChangesFocus(True)
        field("DESCRIPTION (OPTIONAL)", self.description_input)

        specs = QHBoxLayout()
        specs.setSpacing(10)
        self.density_input = QLineEdit()
        self.fe_ppm_input = QLineEdit()
        for label, widget in (("DENSITY (RHO)", self.density_input), ("FE [PPM]", self.fe_ppm_input)):
            col = QVBoxLayout()
            col.setSpacing(4)
            lbl = QLabel(label)
            lbl.setObjectName("FieldLabel")
            col.addWidget(lbl)
            col.addWidget(widget)
            specs.addLayout(col)
        root.addLayout(specs)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        self.create_btn = QPushButton("Create project")
        self.create_btn.setDefault(True)
        self.create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_btn.setEnabled(False)
        self.create_btn.clicked.connect(self._create)
        self.name_input.textChanged.connect(
            lambda text: self.create_btn.setEnabled(bool(text.strip())))
        buttons.addWidget(cancel)
        buttons.addWidget(self.create_btn)
        root.addSpacing(6)
        root.addLayout(buttons)
        self.name_input.setFocus()

    def _show_color(self) -> None:
        self.color_btn.setStyleSheet(
            f"background: {self.color}; border: 1px solid #D8E2E8;"
            " border-radius: 8px; min-width: 0px; padding: 9px 0px;")
        self.color_hint.setText(self.color)

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.color), self, "Choose project color")
        if color.isValid():
            self.color = color.name()
            self._show_color()

    def _create(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            return
        if not self.projects_manager.add_project(
            name, self.color, self.description_input.toPlainText().strip(),
            self.density_input.text().strip(), self.fe_ppm_input.text().strip(),
            self.owner_input.text().strip(),
        ):
            if name in set(self.projects_manager.get_archived_projects()):
                QMessageBox.information(
                    self, "Project archived",
                    f"'{name}' already exists but is archived. Select it in the "
                    "archived projects and click Restore to bring it back.")
            else:
                QMessageBox.information(self, "Project exists", f"'{name}' already exists.")
            return  # stay open so the name can be changed
        self.created_name = name
        self.accept()
