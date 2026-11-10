"""
Borehole Map Manager - Interactive map for placing and viewing boreholes on a project site
"""

import tempfile
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QDoubleSpinBox, QMessageBox, QListWidget, QListWidgetItem
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import Qt, QUrl, QTimer
from project_manager import ProjectManager, Borehole

try:
    import folium
    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False


class BoreholePlacementMap(QDialog):
    """Dialog for placing boreholes on a project site map"""

    def __init__(self, project_name: str, pm: ProjectManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Place Boreholes - {project_name}")
        self.setGeometry(100, 100, 1200, 800)

        self.project_name = project_name
        self.pm = pm
        self.project = pm.get_project(project_name)
        self.selected_coords = None
        self._build_ui()

    def _build_ui(self):
        """Build the UI"""
        layout = QVBoxLayout(self)

        # ── Title and info ──
        title = QLabel(f"Place Boreholes on {self.project_name}")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #e74c3c;")
        layout.addWidget(title)

        info = QLabel("Click on the map to place a borehole. Fill in boring details and save.")
        info.setStyleSheet("font-size: 10px; color: #999;")
        layout.addWidget(info)

        # ── Main content: Map on left, borehole list on right ──
        content_layout = QHBoxLayout()

        # Left: Map
        self.web_view = QWebEngineView()
        self.web_view.setUrl(QUrl.fromLocalFile(self._create_site_map()))
        content_layout.addWidget(self.web_view, 2)

        # Right: Borehole management panel
        right_layout = QVBoxLayout()

        # Borehole input section
        right_layout.addWidget(QLabel("New Borehole Details:"))
        right_layout.addWidget(QLabel("Boring Name:"))
        self.boring_name_input = QLineEdit()
        self.boring_name_input.setPlaceholderText("e.g., BH-01, CPT-A")
        right_layout.addWidget(self.boring_name_input)

        right_layout.addWidget(QLabel("Boring Type:"))
        self.boring_type_combo = QComboBox()
        self.boring_type_combo.addItems(["CPT", "SPT", "Other"])
        right_layout.addWidget(self.boring_type_combo)

        right_layout.addWidget(QLabel("Depth (m):"))
        self.depth_input = QDoubleSpinBox()
        self.depth_input.setRange(0, 100)
        self.depth_input.setValue(10)
        right_layout.addWidget(self.depth_input)

        right_layout.addWidget(QLabel("Coordinates (auto-filled on map click):"))
        self.coords_label = QLabel("Click on map to set coordinates")
        self.coords_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        right_layout.addWidget(self.coords_label)

        # Save button
        save_btn = QPushButton("Save Borehole")
        save_btn.clicked.connect(self._save_borehole)
        right_layout.addWidget(save_btn)

        right_layout.addWidget(QLabel("Existing Boreholes:"))
        self.borehole_list = QListWidget()
        self._refresh_borehole_list()
        right_layout.addWidget(self.borehole_list)

        # Delete button
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self._delete_borehole)
        right_layout.addWidget(delete_btn)

        right_layout.addStretch()

        # Add right panel to main content
        content_layout.addLayout(right_layout, 1)
        layout.addLayout(content_layout, 1)

        # ── Buttons ──
        button_layout = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addStretch()
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)

    def _create_site_map(self) -> str:
        """Create folium map of the project site with boreholes"""
        if not FOLIUM_AVAILABLE:
            return self._create_fallback_map()

        # Center on project location
        center_lat = self.project.location.latitude
        center_lon = self.project.location.longitude

        # Create map zoomed in on site
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=16,
            tiles="OpenStreetMap"
        )

        # Add project center marker
        folium.Marker(
            location=[center_lat, center_lon],
            popup=f"<b>{self.project_name}</b>",
            icon=folium.Icon(color="blue", icon="info-sign"),
            tooltip="Project Location"
        ).add_to(m)

        # Add existing boreholes
        for borehole in self.pm.get_boreholes(self.project_name):
            color = "red" if borehole.boring_type == "CPT" else "green"
            folium.Marker(
                location=[borehole.latitude, borehole.longitude],
                popup=f"<b>{borehole.boring_name}</b><br/>{borehole.boring_type}<br/>Depth: {borehole.depth}m",
                icon=folium.Icon(color=color, icon="info-sign"),
                tooltip=borehole.boring_name
            ).add_to(m)

        # Add click handler JavaScript
        m.add_child(folium.LatLngPopup())

        # Save map to temporary file
        temp_dir = Path(tempfile.gettempdir()) / ".dam_maps"
        temp_dir.mkdir(exist_ok=True)
        map_file = temp_dir / "borehole_map.html"
        m.save(str(map_file))
        return str(map_file)

    def _create_fallback_map(self) -> str:
        """Create fallback HTML map"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Borehole Map</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                .info { background: #f0f0f0; padding: 15px; border-radius: 5px; }
            </style>
        </head>
        <body>
            <div class="info">
                <h2>Borehole Map</h2>
                <p>Install folium for interactive maps:</p>
                <code>pip install folium</code>
            </div>
        </body>
        </html>
        """
        temp_dir = Path(tempfile.gettempdir()) / ".dam_maps"
        temp_dir.mkdir(exist_ok=True)
        map_file = temp_dir / "borehole_map.html"
        map_file.write_text(html)
        return str(map_file)

    def _refresh_borehole_list(self):
        """Refresh the list of boreholes"""
        self.borehole_list.clear()
        for borehole in self.pm.get_boreholes(self.project_name):
            item_text = f"{borehole.boring_name} ({borehole.boring_type}) - {borehole.depth}m"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, borehole.boring_name)
            self.borehole_list.addItem(item)

    def _save_borehole(self):
        """Save a new borehole"""
        boring_name = self.boring_name_input.text().strip()
        if not boring_name:
            QMessageBox.warning(self, "Warning", "Enter a boring name")
            return

        # For now, we'll prompt for coordinates since map clicking isn't implemented yet
        # TODO: Implement map click handler to set coordinates
        QMessageBox.information(self, "Info",
            "Borehole mapping system initialized.\n\n"
            "Click on the map to place boreholes (feature in development).\n\n"
            "For now, use the Project Manager to set borehole locations.")

    def _delete_borehole(self):
        """Delete selected borehole"""
        item = self.borehole_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Warning", "Select a borehole to delete")
            return

        boring_name = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete borehole '{boring_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.pm.delete_borehole(self.project_name, boring_name)
            self._refresh_borehole_list()
            # Refresh map
            self.web_view.setUrl(QUrl.fromLocalFile(self._create_site_map()))
