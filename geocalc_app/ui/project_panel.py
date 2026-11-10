"""
GeoCalc Pro - Project Panel
Create, list, select, and manage projects.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QListWidget, QListWidgetItem, QFrame,
    QDialog, QDialogButtonBox, QFormLayout, QMessageBox, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont

from geocalc_app.core.database import (
    create_project, list_projects, delete_project, get_project,
    get_project_borings
)


class ProjectPanel(QWidget):
    project_selected = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: Project list ────────────────────────────────────────────────
        left = QFrame()
        left.setObjectName("panelFrame")
        left_layout = QVBoxLayout(left)

        header = QLabel("Projects")
        header.setObjectName("panelTitle")
        left_layout.addWidget(header)

        # Search
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍  Search projects...")
        self.search_box.textChanged.connect(self._filter_projects)
        left_layout.addWidget(self.search_box)

        self.project_list = QListWidget()
        self.project_list.setObjectName("projectList")
        self.project_list.itemClicked.connect(self._on_project_click)
        self.project_list.itemDoubleClicked.connect(self._on_project_double_click)
        left_layout.addWidget(self.project_list)

        btn_row = QHBoxLayout()
        self.btn_new = QPushButton("＋  New Project")
        self.btn_new.setObjectName("primaryButton")
        self.btn_new.clicked.connect(self.create_new_project)
        self.btn_delete = QPushButton("🗑  Delete")
        self.btn_delete.setObjectName("dangerButton")
        self.btn_delete.clicked.connect(self._delete_project)
        btn_row.addWidget(self.btn_new)
        btn_row.addWidget(self.btn_delete)
        left_layout.addLayout(btn_row)

        # ── Right: Project detail ─────────────────────────────────────────────
        right = QFrame()
        right.setObjectName("panelFrame")
        right_layout = QVBoxLayout(right)

        detail_header = QLabel("Project Details")
        detail_header.setObjectName("panelTitle")
        right_layout.addWidget(detail_header)

        self.detail_name = QLabel("—")
        self.detail_name.setStyleSheet("font-size: 20px; font-weight: bold; color: #1B3A5C;")
        right_layout.addWidget(self.detail_name)

        form = QFormLayout()
        self.detail_client = QLabel("—")
        self.detail_location = QLabel("—")
        self.detail_created = QLabel("—")
        self.detail_borings = QLabel("—")
        self.detail_cpts = QLabel("—")
        for lbl, widget in [("Client:", self.detail_client),
                             ("Location:", self.detail_location),
                             ("Created:", self.detail_created),
                             ("Borings:", self.detail_borings),
                             ("CPT Soundings:", self.detail_cpts)]:
            form.addRow(QLabel(lbl), widget)
        right_layout.addLayout(form)

        self.detail_description = QLabel("Select a project to view details")
        self.detail_description.setWordWrap(True)
        self.detail_description.setStyleSheet("color: #666; margin-top: 12px;")
        right_layout.addWidget(self.detail_description)

        btn_open = QPushButton("Open Project →")
        btn_open.setObjectName("primaryButton")
        btn_open.clicked.connect(self._open_selected_project)
        right_layout.addWidget(btn_open)
        right_layout.addStretch()

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([400, 600])
        layout.addWidget(splitter)

        self._projects_cache = []
        self._selected_project_id = None

    def refresh(self):
        self._projects_cache = list_projects()
        self._render_list(self._projects_cache)

    def _render_list(self, projects: list):
        self.project_list.clear()
        for p in projects:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, p["id"])
            boring_ct = p.get("boring_count", 0)
            cpt_ct = p.get("cpt_count", 0)
            item.setText(
                f"{p['name']}\n"
                f"  {p.get('client') or 'No client'} · "
                f"{boring_ct} boring{'s' if boring_ct != 1 else ''}, "
                f"{cpt_ct} CPT"
            )
            item.setSizeHint(QSize(0, 55))
            self.project_list.addItem(item)

    def _filter_projects(self, text: str):
        filtered = [p for p in self._projects_cache
                    if text.lower() in p["name"].lower()
                    or text.lower() in (p.get("client") or "").lower()]
        self._render_list(filtered)

    def _on_project_click(self, item: QListWidgetItem):
        pid = item.data(Qt.ItemDataRole.UserRole)
        self._selected_project_id = pid
        project = get_project(pid)
        if project:
            self.detail_name.setText(project["name"])
            self.detail_client.setText(project.get("client") or "—")
            self.detail_location.setText(project.get("location") or "—")
            self.detail_created.setText(project.get("created_at", "—")[:10])
            boring_ct = next((p["boring_count"] for p in self._projects_cache if p["id"] == pid), 0)
            cpt_ct = next((p["cpt_count"] for p in self._projects_cache if p["id"] == pid), 0)
            self.detail_borings.setText(str(boring_ct))
            self.detail_cpts.setText(str(cpt_ct))
            self.detail_description.setText(project.get("description") or "No description.")

    def _on_project_double_click(self, item: QListWidgetItem):
        pid = item.data(Qt.ItemDataRole.UserRole)
        self.project_selected.emit(pid)

    def _open_selected_project(self):
        if self._selected_project_id:
            self.project_selected.emit(self._selected_project_id)

    def create_new_project(self):
        dialog = NewProjectDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            pid = create_project(
                name=dialog.name_edit.text().strip(),
                description=dialog.desc_edit.toPlainText().strip(),
                client=dialog.client_edit.text().strip(),
                location=dialog.location_edit.text().strip(),
            )
            self.refresh()
            self.project_selected.emit(pid)

    def _delete_project(self):
        if not self._selected_project_id:
            return
        project = get_project(self._selected_project_id)
        if not project:
            return
        reply = QMessageBox.question(
            self, "Delete Project",
            f"Permanently delete project '{project['name']}' and ALL associated data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_project(self._selected_project_id)
            self._selected_project_id = None
            self.refresh()


class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h3>Create New Project</h3>"))

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Brickell Tower Foundation Study")
        self.client_edit = QLineEdit()
        self.client_edit.setPlaceholderText("e.g. Miami Development Corp")
        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("e.g. Miami, FL")
        self.desc_edit = QTextEdit()
        self.desc_edit.setFixedHeight(80)
        self.desc_edit.setPlaceholderText("Project notes and description...")

        form.addRow("Project Name *", self.name_edit)
        form.addRow("Client", self.client_edit)
        form.addRow("Location", self.location_edit)
        form.addRow("Description", self.desc_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validation", "Project name is required.")
            return
        self.accept()
