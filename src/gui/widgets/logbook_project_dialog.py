"""Create an IC Logbook project: its name and its column list.

Starts from the 11 standard columns; columns can be renamed, reordered by
dragging their handle, removed (except IC_ID and Test length) and added. Built-in columns keep their type (the
database column is typed); added ones can be text, number or date.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from src.data.logbook_manager import BUILTIN_TYPES, LOCKED_FIELDS, STANDARD_COLUMNS
from src.gui.styles.dialog_styles import DIALOG_STYLE
from src.gui.widgets.confirm_dialog import ConfirmDialog
from src.gui.widgets.edit_row_dialog import ProjectComboBox

_TYPES = [("Text", "text"), ("Number", "number"), ("Date", "date")]
_NAME_MAX = 64  # icm.ic_logbook.category is NVARCHAR(64)

_STYLE = DIALOG_STYLE + (
    "QLabel#FieldLabel { color:#000000; }"
    "QLineEdit { border-radius:2px; }"
)
# Size lives in the style sheet: a style sheet's min-width overrides setFixedSize.
_ICON_BTN = (
    "QPushButton { background:transparent; border:1px solid #D8E2E8; border-radius:2px;"
    " min-width:28px; max-width:28px; min-height:28px; max-height:28px;"
    " padding:0px; color:#000000; font-size:12px; }"
    " QPushButton:hover { background:#EDF2F4; }"
    " QPushButton:disabled { color:#C2CBD1; border-color:#ECEFF2; }"
)
_ADD_BTN = (
    "QPushButton { background:#EEF4F6; color:#000000; border:1px solid #D8E2E8;"
    " border-radius:3px; padding:6px 14px; font-size:12px; font-weight:600; min-width:0px; }"
    " QPushButton:hover { background:#DCEBEB; border-color:#8FCFCF; }"
)


_ROW_DRAGGING = "QWidget#ColumnRow { background:#E4F2F2; border-radius:2px; }"


class _DragHandle(QLabel):
    """The ⠿ grip of a column row: dragging it reorders the row live."""

    def __init__(self, on_drag, on_drop):
        super().__init__("⠿")
        self._on_drag, self._on_drop = on_drag, on_drop
        self.setFixedWidth(22)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("font-size:18px; color:#000000;")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to reorder")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._on_drag(None)  # drag starts
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._on_drag(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._on_drop()


class ProjectDialog(QDialog):
    """Name + editable column list; ``created`` holds the new name on success."""

    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.created = None
        self._entries = []  # dict(field_key, label, type, widget), in display order
        self._build()

    def _build(self):
        self.setWindowTitle("Add project")
        self.setModal(True)
        self.resize(640, 680)
        self.setMinimumSize(520, 460)
        self.setStyleSheet(_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(8)

        title = QLabel("Add project")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#000000;")
        root.addWidget(title)

        name_row = QHBoxLayout()
        lab = QLabel("Name")
        lab.setObjectName("FieldLabel")
        lab.setFixedWidth(70)
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(_NAME_MAX)
        self.name_edit.setPlaceholderText("Project name")
        name_row.addWidget(lab)
        name_row.addWidget(self.name_edit, 1)
        root.addLayout(name_row)

        cols_lbl = QLabel("Columns")
        cols_lbl.setStyleSheet("font-size:11px; font-weight:600; color:#000000;")
        root.addWidget(cols_lbl)

        host = QWidget()
        self._list = QVBoxLayout(host)
        self._list.setContentsMargins(6, 6, 6, 6)
        self._list.setSpacing(4)
        self._list.addStretch(1)  # rows go above it
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.StyledPanel)
        scroll.setStyleSheet("QScrollArea { border:1px solid #E1E8ED; border-radius:2px;"
                             " background:#FAFCFD; }")
        scroll.setWidget(host)
        self._scroll = scroll
        root.addWidget(scroll, 1)

        for field, label in STANDARD_COLUMNS:
            self._add_row(field, label, BUILTIN_TYPES.get(field, "text"))

        add = QPushButton("+  Add column")
        add.setStyleSheet(_ADD_BTN)
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(lambda: self._add_row(focus=True))
        root.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        create = QPushButton("Create project")
        create.setDefault(True)
        create.clicked.connect(self._on_create)
        buttons.addWidget(cancel)
        buttons.addWidget(create)
        root.addLayout(buttons)

    # ------------------------------------------------------------ Rows
    def _add_row(self, field_key=None, label="", data_type="text", focus=False):
        builtin = field_key is not None
        row = QWidget()
        row.setObjectName("ColumnRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        name = QLineEdit(label)
        name.setPlaceholderText("Column name")
        type_combo = ProjectComboBox()
        type_combo.setObjectName("ProjectField")
        for text, value in _TYPES:
            type_combo.addItem(text, value)
        type_combo.setCurrentIndex(type_combo.findData(data_type))
        type_combo.setFixedWidth(120)
        # Built-in columns keep their type: number/date ones are typed in the
        # database, and retyping a text one would make existing values (e.g. a
        # path in "Archived in") invalid and get wiped on the next save.
        if builtin:
            type_combo.setEnabled(False)
            type_combo.setStyleSheet(
                "QComboBox#ProjectField:disabled { color:#8A97A0; background:#EEF2F4; }")
            type_combo._arrow.hide()  # a locked field shouldn't look openable
            type_combo.setToolTip("Built-in column: its type is fixed. "
                                  "Add a new column to choose a type.")
        remove = QPushButton("✕")
        remove.setStyleSheet(_ICON_BTN)
        remove.setAutoDefault(False)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        if field_key in LOCKED_FIELDS:
            remove.setEnabled(False)
            remove.setToolTip("Every project needs this column.")
        else:
            remove.setToolTip("Remove this column")
        entry = {"field_key": field_key, "label": name, "type": type_combo, "widget": row}
        handle = _DragHandle(lambda pos: self._drag(entry, pos),
                             lambda: self._drop(entry))
        remove.clicked.connect(lambda: self._remove(entry))
        lay.addWidget(handle)
        lay.addWidget(name, 1)
        lay.addWidget(type_combo)
        lay.addWidget(remove)
        self._entries.append(entry)
        self._list.insertWidget(self._list.count() - 1, row)  # above the stretch
        if focus:
            name.setFocus()

    def _drag(self, entry, global_pos) -> None:
        """Move ``entry`` to where the cursor is; None marks the drag start."""
        row = entry["widget"]
        if global_pos is None:
            row.setStyleSheet(_ROW_DRAGGING)
            return
        host = row.parentWidget()
        y = host.mapFromGlobal(global_pos).y()
        others = [e for e in self._entries if e is not entry]
        target = sum(1 for e in others if e["widget"].geometry().center().y() < y)
        if others[target:target + 1] != [entry] and self._entries.index(entry) != target:
            self._entries = others[:target] + [entry] + others[target:]
            self._list.removeWidget(row)
            self._list.insertWidget(target, row)
            self._list.activate()  # settle geometries before the next move
        # Scroll along when the cursor nears the top or bottom of the list.
        view_y = self._scroll.viewport().mapFromGlobal(global_pos).y()
        bar = self._scroll.verticalScrollBar()
        if view_y < 20:
            bar.setValue(bar.value() - 12)
        elif view_y > self._scroll.viewport().height() - 20:
            bar.setValue(bar.value() + 12)

    def _drop(self, entry) -> None:
        entry["widget"].setStyleSheet("")

    def _remove(self, entry) -> None:
        self._entries.remove(entry)
        entry["widget"].hide()
        entry["widget"].deleteLater()

    # ------------------------------------------------------------ Save
    def _on_create(self):
        name = self.name_edit.text().strip()
        problem = self.manager.validate_project_name(name)
        if problem:
            QMessageBox.warning(self, "Project name", problem)
            return
        labels = [e["label"].text().strip() for e in self._entries]
        if not all(labels):
            QMessageBox.warning(self, "Column name missing", "Every column needs a name.")
            return
        dupes = sorted({l for l in labels if [x.lower() for x in labels].count(l.lower()) > 1})
        if dupes:
            QMessageBox.warning(self, "Duplicate column",
                                f"Column names must be unique: {', '.join(dupes)}.")
            return
        columns = [{
            "field_key": e["field_key"] or self.manager.new_custom_key(),
            "label": label,
            "data_type": e["type"].currentData(),
        } for e, label in zip(self._entries, labels)]
        error = self.manager.add_project(name, columns)
        if error:
            QMessageBox.warning(self, "Could not create the project", error)
            return
        self.created = name
        self.accept()


_LIST = (
    "QListWidget { background:#FFFFFF; border:1px solid #D8E2E8; border-radius:2px;"
    " font-size:13px; color:#000000; outline:0; }"
    " QListWidget::item { padding:6px 8px; }"
    " QListWidget::item:selected { background:#BFE6E6; color:#000000; }"
    " QListWidget::item:hover:!selected { background:#EEF6F6; }"
)


class ManageProjectsDialog(QDialog):
    """Active / archived project lists, plus rename. Projects are archived, never
    deleted; changes are held until "Save and close"."""

    _ORIGINAL = Qt.ItemDataRole.UserRole  # each item's name before any rename here

    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._original = set(manager.get_project_names(archived=True))
        self.saved = False
        self._build()

    def _build(self):
        self.setWindowTitle("Manage projects")
        self.setModal(True)
        self.resize(720, 560)
        self.setMinimumSize(560, 400)
        self.setStyleSheet(_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)

        title = QLabel("Manage projects")
        title.setStyleSheet("font-size:16px; font-weight:700; color:#000000;")
        root.addWidget(title)

        self.active = self._list()
        self.archived = self._list()
        self._fill(self.active, self.manager.get_project_names(archived=False))
        self._fill(self.archived, self.manager.get_project_names(archived=True))
        self.active.itemDoubleClicked.connect(lambda _i: self._move(self.active, self.archived))
        self.archived.itemDoubleClicked.connect(lambda _i: self._move(self.archived, self.active))

        archive = QPushButton("Archive  →")
        archive.clicked.connect(lambda: self._move(self.active, self.archived))
        restore = QPushButton("←  Restore")
        restore.clicked.connect(lambda: self._move(self.archived, self.active))
        rename = QPushButton("Rename…")
        rename.clicked.connect(self._rename)
        middle = QVBoxLayout()
        middle.addStretch(1)
        for b in (archive, restore, rename):
            b.setAutoDefault(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            middle.addWidget(b)
        middle.addStretch(1)

        lists = QHBoxLayout()
        lists.setSpacing(12)
        lists.addLayout(self._column("Active projects", self.active), 1)
        lists.addLayout(middle)
        lists.addLayout(self._column("Archived projects", self.archived), 1)
        root.addLayout(lists, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save and close")
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    @staticmethod
    def _list() -> QListWidget:
        lst = QListWidget()
        lst.setStyleSheet(_LIST)
        lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        return lst

    def _fill(self, lst: QListWidget, names) -> None:
        for name in names:
            item = QListWidgetItem(name)
            item.setData(self._ORIGINAL, name)
            lst.addItem(item)

    @staticmethod
    def _column(label: str, lst: QListWidget) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(4)
        cap = QLabel(label)
        cap.setStyleSheet("font-size:12px; font-weight:600; color:#000000;")
        col.addWidget(cap)
        col.addWidget(lst, 1)
        return col

    @staticmethod
    def _items(lst: QListWidget) -> list:
        return [lst.item(i) for i in range(lst.count())]

    def _move(self, src: QListWidget, dst: QListWidget) -> None:
        moved = [src.takeItem(src.row(item)) for item in src.selectedItems()]
        items = self._items(dst) + moved
        # Keep the logbook's tab order (by original name) in both lists.
        order = {n: i for i, n in enumerate(self.manager.get_categories(include_archived=True))}
        items.sort(key=lambda it: order.get(it.data(self._ORIGINAL), len(order)))
        while dst.count():
            dst.takeItem(0)
        for item in items:
            dst.addItem(item)

    def _rename(self) -> None:
        selected = self.active.selectedItems() + self.archived.selectedItems()
        if len(selected) != 1:
            QMessageBox.information(self, "Rename", "Select one project to rename.")
            return
        if not self.manager.can_rename():
            QMessageBox.information(
                self, "Not available yet",
                "Renaming projects needs database migration 022. Please run it first.")
            return
        item = selected[0]
        new, ok = QInputDialog.getText(self, "Rename project", "New name:", text=item.text())
        new = new.strip()
        if not ok or new == item.text():
            return
        problem = self.manager.validate_project_name(new, taken=self._taken_names(item))
        if problem:
            QMessageBox.warning(self, "Project name", problem)
            return
        item.setText(new)

    def _taken_names(self, item) -> list:
        """Every other project as named in this window, plus categories that
        exist only in the data."""
        projects = (set(self.manager.get_project_names(archived=False))
                    | set(self.manager.get_project_names(archived=True)))
        others = [it.text() for it in self._items(self.active) + self._items(self.archived)
                  if it is not item]
        return others + [c for c in self.manager.get_categories(include_archived=True)
                         if c not in projects]

    def _renames(self) -> dict:
        return {it.data(self._ORIGINAL): it.text()
                for it in self._items(self.active) + self._items(self.archived)
                if it.text() != it.data(self._ORIGINAL)}

    def _archive_changes(self) -> dict:
        """{current name: archived} for projects whose archived state changed."""
        archived_now = {it.data(self._ORIGINAL) for it in self._items(self.archived)}
        current = {it.data(self._ORIGINAL): it.text()
                   for it in self._items(self.active) + self._items(self.archived)}
        return {current[o]: o in archived_now for o in archived_now ^ self._original}

    def _save(self):
        renames, archived = self._renames(), self._archive_changes()
        if renames or archived:
            error = self.manager.apply_project_changes(renames, archived)
            if error:
                QMessageBox.warning(self, "Could not save", error)
                # Some changes may be in already: close so the tabs refresh.
        self.saved = bool(renames or archived)
        self.accept()

    def reject(self):
        # Cancel, Escape and the window's X all land here.
        if (self._renames() or self._archive_changes()) and not ConfirmDialog.ask(
                self, title="Discard changes?",
                message="Discard your changes to the projects?",
                confirm_text="Discard", cancel_text="Keep editing", destructive=True):
            return
        super().reject()
