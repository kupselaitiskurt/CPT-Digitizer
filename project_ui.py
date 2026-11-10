"""
Project Manager UI Module for D.A.M. Application
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QDoubleSpinBox, QDialog,
    QScrollArea, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QFileDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal
from project_manager import ProjectManager, Project

try:
    from ags_handler import AGS41Handler
    AGS_AVAILABLE = True
except ImportError:
    AGS_AVAILABLE = False

try:
    from map_view_enhanced import MapViewWidget
    MAP_AVAILABLE = True
except ImportError:
    MAP_AVAILABLE = False

try:
    from borehole_map import BoreholePlacementMap
    BOREHOLE_MAP_AVAILABLE = True
except ImportError:
    BOREHOLE_MAP_AVAILABLE = False


class CreateProjectDialog(QDialog):
    """Dialog to create a new project"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.setMinimumWidth(400)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Project name
        layout.addWidget(QLabel("Project Name:"))
        self.name_input = QLineEdit()
        layout.addWidget(self.name_input)

        # Address
        layout.addWidget(QLabel("Address/Location:"))
        self.address_input = QLineEdit()
        layout.addWidget(self.address_input)

        # Latitude
        layout.addWidget(QLabel("Latitude:"))
        self.lat_input = QDoubleSpinBox()
        self.lat_input.setRange(-90, 90)
        self.lat_input.setValue(0)
        layout.addWidget(self.lat_input)

        # Longitude
        layout.addWidget(QLabel("Longitude:"))
        self.lon_input = QDoubleSpinBox()
        self.lon_input.setRange(-180, 180)
        self.lon_input.setValue(0)
        layout.addWidget(self.lon_input)

        # Description
        layout.addWidget(QLabel("Description:"))
        self.desc_input = QLineEdit()
        layout.addWidget(self.desc_input)

        # Buttons
        button_layout = QHBoxLayout()
        create_btn = QPushButton("Create")
        create_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(create_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def get_data(self):
        return {
            "name": self.name_input.text(),
            "address": self.address_input.text(),
            "latitude": self.lat_input.value(),
            "longitude": self.lon_input.value(),
            "description": self.desc_input.text(),
        }


class ProjectManagerUI(QWidget):
    """Project Manager UI Module"""

    project_selected = pyqtSignal(str)  # Emits project name

    def __init__(self):
        super().__init__()
        self.pm = ProjectManager()
        self.current_project = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("Project Manager")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #e74c3c;")
        layout.addWidget(title)

        # Main content: Splitter with list on left, map on right
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # ── Left side: Project List ──
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Projects table
        left_layout.addWidget(QLabel("Projects:"))
        self.project_table = QTableWidget()
        self.project_table.setColumnCount(3)
        self.project_table.setHorizontalHeaderLabels(["Project Name", "Address", "Coordinates"])
        self.project_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.project_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.project_table.itemClicked.connect(self._on_project_table_selected)
        self.project_table.horizontalHeader().setStretchLastSection(True)
        left_layout.addWidget(self.project_table)

        # Button row
        button_layout = QHBoxLayout()
        new_btn = QPushButton("+ New Project")
        new_btn.clicked.connect(self._create_new_project)
        button_layout.addWidget(new_btn)

        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self._delete_project)
        button_layout.addWidget(delete_btn)

        # Manage boreholes button
        if BOREHOLE_MAP_AVAILABLE:
            boreholes_btn = QPushButton("📍 Manage Boreholes")
            boreholes_btn.clicked.connect(self._open_borehole_map)
            button_layout.addWidget(boreholes_btn)

        left_layout.addLayout(button_layout)

        # Project details
        left_layout.addWidget(QLabel("Project Details:"))
        self.details_text = QLineEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMinimumHeight(80)
        left_layout.addWidget(self.details_text)

        # AGS Export/Import buttons
        if AGS_AVAILABLE:
            ags_button_layout = QHBoxLayout()
            export_ags_btn = QPushButton("📋 Export to AGS 4.1")
            export_ags_btn.clicked.connect(self._export_to_ags)
            ags_button_layout.addWidget(export_ags_btn)

            import_ags_btn = QPushButton("📥 Import AGS 4.1")
            import_ags_btn.clicked.connect(self._import_from_ags)
            ags_button_layout.addWidget(import_ags_btn)

            left_layout.addLayout(ags_button_layout)

        splitter.addWidget(left_widget)

        # ── Right side: Map (if available) ──
        if MAP_AVAILABLE:
            self.map_widget = MapViewWidget(self.pm)
            self.map_widget.project_selected.connect(self._on_map_project_selected)
            splitter.addWidget(self.map_widget)
            splitter.setSizes([400, 600])  # Left: 400, Right: 600
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)

        # Populate project list - don't refresh map yet, it will refresh itself
        self._refresh_project_list(refresh_map=False)

    def _refresh_project_list(self, refresh_map=True):
        """Refresh the project list display"""
        self.project_table.setRowCount(0)
        for proj_name in self.pm.list_projects():
            project = self.pm.get_project(proj_name)
            if project:
                row = self.project_table.rowCount()
                self.project_table.insertRow(row)

                # Project name
                name_item = QTableWidgetItem(proj_name)
                self.project_table.setItem(row, 0, name_item)

                # Address
                address = project.location.address if project.location else ""
                addr_item = QTableWidgetItem(address)
                self.project_table.setItem(row, 1, addr_item)

                # Coordinates
                if project.location:
                    coords = f"{project.location.latitude:.4f}, {project.location.longitude:.4f}"
                else:
                    coords = "N/A"
                coords_item = QTableWidgetItem(coords)
                self.project_table.setItem(row, 2, coords_item)

        # Refresh map only if requested (skip on initial load to avoid double refresh)
        if refresh_map and MAP_AVAILABLE and hasattr(self, 'map_widget'):
            self.map_widget.refresh()

    def _on_project_table_selected(self, item):
        """Handle project selection from table"""
        row = item.row()
        proj_name = self.project_table.item(row, 0).text()
        project = self.pm.get_project(proj_name)
        if project:
            self.current_project = proj_name
            details = f"""
Name: {project.name}
Location: {project.location.address}
Coordinates: {project.location.latitude:.4f}, {project.location.longitude:.4f}
Created: {project.created_date[:10]}
Description: {project.description}
            """
            self.details_text.setText(details.strip())
            self.project_selected.emit(proj_name)

    def _on_map_project_selected(self, proj_name: str):
        """Handle project selection from map"""
        # Find and select the project in the table
        for row in range(self.project_table.rowCount()):
            item = self.project_table.item(row, 0)
            if item.text() == proj_name:
                self.project_table.selectRow(row)
                self._on_project_table_selected(item)
                break

    def _create_new_project(self):
        """Create a new project"""
        dialog = CreateProjectDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            try:
                self.pm.create_project(
                    name=data["name"],
                    latitude=data["latitude"],
                    longitude=data["longitude"],
                    address=data["address"],
                    description=data["description"],
                )
                self._refresh_project_list()
                QMessageBox.information(self, "Success", f"Project '{data['name']}' created!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create project: {e}")

    def _delete_project(self):
        """Delete selected project"""
        selected_rows = self.project_table.selectedIndexes()
        if not selected_rows:
            QMessageBox.warning(self, "Warning", "Select a project first")
            return

        row = selected_rows[0].row()
        proj_name = self.project_table.item(row, 0).text()

        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete project '{proj_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.pm.delete_project(proj_name)
            self.current_project = None
            self._refresh_project_list()

    def _open_borehole_map(self):
        """Open borehole placement map for selected project"""
        if not self.current_project:
            QMessageBox.warning(self, "Warning", "Select a project first")
            return

        if not BOREHOLE_MAP_AVAILABLE:
            QMessageBox.warning(self, "Warning", "Borehole map module not available")
            return

        dialog = BoreholePlacementMap(self.current_project, self.pm, self)
        dialog.exec()
        # Refresh map after closing borehole map
        if hasattr(self, 'map_widget'):
            self.map_widget.refresh()

    def _export_to_ags(self):
        """Export project to AGS 4.1 format"""
        if not self.current_project:
            QMessageBox.warning(self, "Warning", "Select a project first")
            return

        if not AGS_AVAILABLE:
            QMessageBox.warning(self, "Warning", "AGS handler not available")
            return

        # File dialog
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export Project to AGS 4.1",
            f"{self.current_project}.ags",
            "AGS Files (*.ags)"
        )

        if not filepath:
            return

        # Export
        success = AGS41Handler.export_project_to_ags(self.current_project, self.pm, filepath)
        if success:
            QMessageBox.information(self, "Success", f"Project exported to:\n{filepath}")
        else:
            QMessageBox.critical(self, "Error", "Failed to export project")

    def _import_from_ags(self):
        """Import boreholes from AGS 4.1 file"""
        if not self.current_project:
            QMessageBox.warning(self, "Warning", "Select a project first")
            return

        if not AGS_AVAILABLE:
            QMessageBox.warning(self, "Warning", "AGS handler not available")
            return

        # File dialog
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Import AGS 4.1 File",
            "",
            "AGS Files (*.ags)"
        )

        if not filepath:
            return

        # Import
        success = AGS41Handler.import_boreholes_from_ags(filepath, self.pm, self.current_project)
        if success:
            QMessageBox.information(self, "Success", "Boreholes imported from AGS file")
            # Refresh the borehole list
            if hasattr(self, 'map_widget'):
                self.map_widget.refresh()
        else:
            QMessageBox.critical(self, "Error", "Failed to import AGS file")
