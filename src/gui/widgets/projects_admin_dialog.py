"""Dialog to administer the configurable list of projects.

Lets the user add, rename, recolor and remove projects that appear in the
Project ID dropdown of the immersion cell editor. Adding a project and editing
an existing one both happen in a small :class:`ProjectEditorDialog` popup.
Changes are persisted immediately through the provided :class:`ProjectsManager`.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
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


class ProjectEditorDialog(QDialog):
    """Small popup to enter/edit a project's name, color, and description.

    Used both for adding a new project and editing an existing one. On accept,
    the chosen name, color, and description are available via :attr:`name`,
    :attr:`color`, and :attr:`description`.
    """

    def __init__(self, parent=None, name: str = "", color: str | None = None,
                 description: str | None = None, title: str = "Add project"):
        super().__init__(parent)
        self.name = (name or "").strip()
        self.color = color or (
            COLOR_PALETTE[0] if COLOR_PALETTE else DEFAULT_PROJECT_COLOR
        )
        self.description = (description or "").strip()
        self._title_text = title
        self.init_ui()

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        self.setWindowTitle(self._title_text)
        self.setModal(True)
        self.resize(380, 240)

        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(DIALOG_STYLE)

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
        header.setFixedHeight(70)

        layout = QVBoxLayout(header)
        layout.setContentsMargins(24, 14, 24, 14)
        layout.setSpacing(2)

        title = QLabel(self._title_text)
        title.setObjectName("DialogTitle")
        subtitle = QLabel("Choose a name, color, and optional description for the project.")
        subtitle.setObjectName("DialogSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        return header

    def _build_body(self) -> QFrame:
        body = QFrame()
        body.setObjectName("DialogBody")

        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(28, 22, 28, 20)
        body_layout.setSpacing(14)

        name_label = QLabel("PROJECT NAME")
        name_label.setObjectName("FieldLabel")
        self.name_input = QLineEdit(self.name)
        self.name_input.setPlaceholderText("Project name…")
        self.name_input.returnPressed.connect(self._on_save)
        body_layout.addWidget(name_label)
        body_layout.addWidget(self.name_input)

        color_label = QLabel("COLOR")
        color_label.setObjectName("FieldLabel")
        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        self.color_btn = QPushButton()
        self.color_btn.setToolTip("Pick the project color")
        self.color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color_btn.setFixedWidth(46)
        self.color_btn.clicked.connect(self._on_pick_color)
        self._update_color_button()
        self.color_hint = QLabel(self.color)
        self.color_hint.setStyleSheet("color: #4A5A66; font-size: 12px;")
        color_row.addWidget(self.color_btn)
        color_row.addWidget(self.color_hint, 1)
        body_layout.addWidget(color_label)
        body_layout.addLayout(color_row)

        description_label = QLabel("DESCRIPTION (OPTIONAL)")
        description_label.setObjectName("FieldLabel")
        self.description_input = QLineEdit(self.description)
        self.description_input.setPlaceholderText("Add a description…")
        self.description_input.returnPressed.connect(self._on_save)
        body_layout.addWidget(description_label)
        body_layout.addWidget(self.description_input)

        body_layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        body_layout.addLayout(btn_row)

        return body

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

    # ----------------------------------------------------------------- Save
    def _on_save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.information(
                self, "Name required", "Please enter a project name."
            )
            return
        self.name = name
        self.description = self.description_input.text().strip()
        self.accept()

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


class ProjectsAdminDialog(QDialog):
    """A small window to add/edit/remove projects."""

    def __init__(self, projects_manager, parent=None, on_remove=None,
                 on_rename=None):
        super().__init__(parent)
        self.projects_manager = projects_manager
        self._remove_callback = on_remove
        self._rename_callback = on_rename
        self.init_ui()
        self._reload()

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        self.setWindowTitle("Manage Projects")
        self.setModal(True)
        self.resize(420, 480)

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
        subtitle = QLabel("Double-click a project to edit its name, color, and description.")
        subtitle.setObjectName("DialogSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        return header

    def _build_body(self) -> QFrame:
        body = QFrame()
        body.setObjectName("DialogBody")

        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(28, 26, 28, 22)
        body_layout.setSpacing(16)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("ProjectsList")
        self.list_widget.itemDoubleClicked.connect(self._on_edit_project)
        body_layout.addWidget(self.list_widget, 1)

        # Bottom action buttons.
        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add project")
        add_btn.setDefault(True)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._on_add)
        remove_btn = QPushButton("Remove selected")
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.clicked.connect(self._on_remove)
        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        body_layout.addLayout(btn_row)

        return body

    # ----------------------------------------------------------------- Data
    def _reload(self) -> None:
        self.list_widget.clear()
        colors = self.projects_manager.get_project_colors()
        for project in self.projects_manager.get_projects():
            item = QListWidgetItem(
                _swatch(colors.get(project, DEFAULT_PROJECT_COLOR)),
                project,
            )
            self.list_widget.addItem(item)

    def _on_add(self) -> None:
        editor = ProjectEditorDialog(self, title="Add project")
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        if not self.projects_manager.add_project(editor.name, editor.color, editor.description):
            QMessageBox.information(
                self, "Project exists", f"'{editor.name}' already exists."
            )
            return
        self._reload()

    def _on_edit_project(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        old_name = item.text()
        current_color = self.projects_manager.get_color(old_name)
        current_description = self.projects_manager.get_description(old_name)
        editor = ProjectEditorDialog(
            self, name=old_name, color=current_color, description=current_description,
            title="Edit project"
        )
        if editor.exec() != QDialog.DialogCode.Accepted:
            return

        new_name = editor.name
        new_color = editor.color
        new_description = editor.description

        if new_name != old_name:
            # Guard against renaming onto an existing project.
            existing = set(self.projects_manager.get_projects())
            if new_name in existing:
                QMessageBox.information(
                    self, "Project exists", f"'{new_name}' already exists."
                )
                return

        if not self.projects_manager.rename_project(
            old_name, new_name, new_color
        ):
            QMessageBox.warning(
                self, "Update failed", f"Could not update '{old_name}'."
            )
            return

        # Update description if it changed
        if new_description != (self.projects_manager.get_description(old_name) or ""):
            self.projects_manager.set_project_description(new_name, new_description)

        # Cascade a rename to channels and the station history.
        if new_name != old_name and self._rename_callback is not None:
            self._rename_callback(old_name, new_name)

        self._reload()

    def _on_remove(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(
                self, "No selection", "Select a project to remove."
            )
            return
        name = item.text()
        confirm = QMessageBox.question(
            self,
            "Remove project",
            f"Remove project '{name}'?\n\nThis will also clear it from all "
            "channels and from their entry in the station summary.",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            if self._remove_callback is not None:
                self._remove_callback(name)
            self.projects_manager.remove_project(name)
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

