"""
Enhanced Map View for D.A.M. - Real maps with OpenStreetMap/Satellite tiles
Uses Folium to create interactive maps embedded in PyQt
"""

import os
import tempfile
import time
from pathlib import Path
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QTimer
from project_manager import ProjectManager

try:
    import folium
    from folium.plugins import MarkerCluster, HeatMap
    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False


class EnhancedMapView(QWidget):
    """Interactive map with street/satellite tiles showing project locations"""

    project_clicked = pyqtSignal(str)  # Emits project name

    def __init__(self, project_manager=None):
        super().__init__()
        self.pm = project_manager if project_manager is not None else ProjectManager()
        self.map_file = None
        self.web_view = None
        self._build_ui()
        self._is_loading = False
        print(f"[DEBUG] EnhancedMapView initialized, folium available: {FOLIUM_AVAILABLE}")
        # Delay initial refresh to allow UI to fully render
        QTimer.singleShot(200, lambda: self.refresh())

    def _build_ui(self):
        """Build the map UI"""
        layout = QVBoxLayout(self)

        # Controls
        controls = QHBoxLayout()

        satellite_btn = QPushButton("🛰️  Satellite")
        satellite_btn.clicked.connect(lambda: self.refresh(tile_type="satellite"))
        controls.addWidget(satellite_btn)

        street_btn = QPushButton("🗺️  Streets")
        street_btn.clicked.connect(lambda: self.refresh(tile_type="streets"))
        controls.addWidget(street_btn)

        terrain_btn = QPushButton("⛰️  Terrain")
        terrain_btn.clicked.connect(lambda: self.refresh(tile_type="terrain"))
        controls.addWidget(terrain_btn)

        controls.addStretch()
        layout.addLayout(controls)

        # Web view for map
        self.web_view = QWebEngineView()
        settings = self.web_view.settings()
        settings.setAttribute(settings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        print("[DEBUG] QWebEngineView created and JS/Remote URL access enabled")
        layout.addWidget(self.web_view)

    def _create_map(self, tile_type: str = "streets") -> str:
        """Create folium map with project locations"""
        if not FOLIUM_AVAILABLE:
            print("[DEBUG] Folium not available, using fallback map")
            return self._create_fallback_map()

        projects = self.pm.list_projects()
        print(f"[DEBUG] Creating map with {len(projects)} projects")
        if not projects:
            # Default to world view if no projects
            m = folium.Map(location=[20, 0], zoom_start=2)
        else:
            # Calculate center point
            lats = []
            lons = []
            for proj_name in projects:
                project = self.pm.get_project(proj_name)
                if project and project.location:
                    lats.append(project.location.latitude)
                    lons.append(project.location.longitude)

            if lats and lons:
                center_lat = sum(lats) / len(lats)
                center_lon = sum(lons) / len(lons)
                zoom = 13 if len(projects) == 1 else 11
            else:
                center_lat, center_lon, zoom = 20, 0, 2

            # Create map with selected tile
            if tile_type == "satellite":
                m = folium.Map(
                    location=[center_lat, center_lon],
                    zoom_start=zoom,
                    tiles="Esri.WorldImagery",
                    attr="Esri"
                )
            elif tile_type == "terrain":
                m = folium.Map(
                    location=[center_lat, center_lon],
                    zoom_start=zoom,
                    tiles="OpenTopoMap"
                )
            else:  # streets
                m = folium.Map(
                    location=[center_lat, center_lon],
                    zoom_start=zoom,
                    tiles="OpenStreetMap"
                )

            # Add project markers
            for proj_name in projects:
                project = self.pm.get_project(proj_name)
                if project and project.location:
                    lat = project.location.latitude
                    lon = project.location.longitude
                    addr = project.location.address or "Unknown Location"

                    # Create popup with project info
                    popup_text = f"""
                    <b>{proj_name}</b><br/>
                    {addr}<br/>
                    <small>{lat:.4f}, {lon:.4f}</small><br/>
                    <small>Created: {project.created_date[:10]}</small>
                    """

                    # Add marker
                    folium.Marker(
                        location=[lat, lon],
                        popup=folium.Popup(popup_text, max_width=250),
                        icon=folium.Icon(color="red", icon="info-sign"),
                        tooltip=proj_name
                    ).add_to(m)

        # Save map to temporary file
        temp_dir = Path(tempfile.gettempdir()) / ".dam_maps"
        temp_dir.mkdir(exist_ok=True)
        map_file = temp_dir / "project_map.html"

        print(f"[DEBUG] Saving map to: {map_file}")
        m.save(str(map_file))
        print(f"[DEBUG] Map saved successfully")
        return str(map_file)

    def _create_fallback_map(self) -> str:
        """Create a simple HTML map if folium is not available"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Project Map</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                .info { background: #f0f0f0; padding: 15px; border-radius: 5px; }
            </style>
        </head>
        <body>
            <div class="info">
                <h2>🗺️ Project Map</h2>
                <p>Install folium for interactive maps:</p>
                <code>pip install folium</code>
                <p>After installing, restart the application for map functionality.</p>
            </div>
        </body>
        </html>
        """
        temp_dir = Path(tempfile.gettempdir()) / ".dam_maps"
        temp_dir.mkdir(exist_ok=True)
        map_file = temp_dir / "project_map.html"
        map_file.write_text(html)
        return str(map_file)

    def refresh(self, tile_type: str = "streets"):
        """Refresh the map"""
        # Prevent multiple simultaneous refreshes
        if self._is_loading:
            print(f"[DEBUG] Map refresh already in progress, skipping")
            return

        self._is_loading = True
        print(f"[DEBUG] Refreshing map with tile_type: {tile_type}")

        try:
            self.map_file = self._create_map(tile_type)
            print(f"[DEBUG] Map file path: {self.map_file}")

            # Verify file exists
            map_path = Path(self.map_file)
            if not map_path.exists():
                print(f"[DEBUG] ERROR: Map file does not exist at {self.map_file}")
                return

            print(f"[DEBUG] Map file verified, size: {map_path.stat().st_size} bytes")

            if self.web_view:
                # Use QTimer to ensure file is fully flushed before loading
                def load_map():
                    try:
                        url = QUrl.fromLocalFile(self.map_file)
                        print(f"[DEBUG] Loading URL: {url.toString()}")
                        self.web_view.setUrl(url)
                        print(f"[DEBUG] URL set to web_view")
                    finally:
                        self._is_loading = False

                # Small delay to ensure file is flushed
                QTimer.singleShot(100, load_map)
            else:
                print("[DEBUG] ERROR: web_view is None!")
                self._is_loading = False
        except Exception as e:
            print(f"[DEBUG] ERROR in refresh: {e}")
            self._is_loading = False


class MapViewWidget(QWidget):
    """Widget containing enhanced map view"""

    project_selected = pyqtSignal(str)

    def __init__(self, project_manager=None):
        super().__init__()
        self.pm = project_manager
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("Project Locations Map")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #e74c3c;")
        layout.addWidget(title)

        # Info
        info = QLabel("Click on red markers to view project details. Use controls to change map style.")
        info.setStyleSheet("font-size: 10px; color: #666;")
        layout.addWidget(info)

        # Map - pass the ProjectManager instance
        self.map_view = EnhancedMapView(self.pm)
        layout.addWidget(self.map_view)

    def refresh(self):
        """Refresh the map"""
        self.map_view.refresh()
