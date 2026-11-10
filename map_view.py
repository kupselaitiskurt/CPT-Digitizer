"""
Simple Map View for D.A.M. - Shows project locations as clickable points
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGraphicsView, QGraphicsScene, QGraphicsEllipseItem, QGraphicsTextItem
from PyQt6.QtCore import Qt, QPointF, pyqtSignal, QRect
from PyQt6.QtGui import QPen, QColor, QFont, QBrush
from project_manager import ProjectManager


class MapView(QGraphicsView):
    """Interactive map showing project locations"""

    project_clicked = pyqtSignal(str)  # Emits project name

    def __init__(self):
        super().__init__()
        self.pm = ProjectManager()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setStyleSheet("QGraphicsView { background-color: #f0f0f0; border: 1px solid #ccc; }")

        # Map bounds (simplified lat/lon to pixel mapping)
        self.lat_min, self.lat_max = -90, 90
        self.lon_min, self.lon_max = -180, 180
        self.padding = 40

        self.project_points = {}  # {project_name: (x, y)}
        self._draw_map()

    def _draw_map(self):
        """Draw the map with project locations"""
        self.scene.clear()
        self.project_points.clear()

        # Get viewport size
        w, h = 800, 600
        self.setSceneRect(0, 0, w, h)

        # Draw background grid
        for lat in range(-90, 91, 30):
            y = self._lat_to_y(lat, h)
            self.scene.addLine(0, y, w, y, QPen(QColor("#ddd"), 0.5))
            text = self.scene.addText(f"{lat}°")
            text.setPos(-30, y)
            text.setFont(QFont("Arial", 8))

        for lon in range(-180, 181, 60):
            x = self._lon_to_x(lon, w)
            self.scene.addLine(x, 0, x, h, QPen(QColor("#ddd"), 0.5))
            text = self.scene.addText(f"{lon}°")
            text.setPos(x, h + 10)
            text.setFont(QFont("Arial", 8))

        # Draw projects as points
        projects = self.pm.list_projects()
        for proj_name in projects:
            project = self.pm.get_project(proj_name)
            if project and project.location:
                x = self._lon_to_x(project.location.longitude, w)
                y = self._lat_to_y(project.location.latitude, h)
                self.project_points[proj_name] = (x, y)

                # Draw point
                circle = QGraphicsEllipseItem(x - 6, y - 6, 12, 12)
                circle.setPen(QPen(QColor("#e74c3c"), 2))
                circle.setBrush(QBrush(QColor("#e74c3c")))
                circle.setZValue(1)
                self.scene.addItem(circle)

                # Draw label
                label = self.scene.addText(proj_name[:15])
                label.setPos(x + 10, y - 10)
                label.setFont(QFont("Arial", 9))
                label.setZValue(0)

    def _lon_to_x(self, lon: float, width: int) -> float:
        """Convert longitude to x pixel coordinate"""
        normalized = (lon - self.lon_min) / (self.lon_max - self.lon_min)
        return self.padding + normalized * (width - 2 * self.padding)

    def _lat_to_y(self, lat: float, height: int) -> float:
        """Convert latitude to y pixel coordinate (inverted for screen coords)"""
        normalized = (self.lat_max - lat) / (self.lat_max - self.lat_min)
        return self.padding + normalized * (height - 2 * self.padding)

    def mousePressEvent(self, event):
        """Handle click on project point"""
        scene_pos = self.mapToScene(event.pos())
        for proj_name, (px, py) in self.project_points.items():
            dist = ((scene_pos.x() - px)**2 + (scene_pos.y() - py)**2)**0.5
            if dist < 12:
                self.project_clicked.emit(proj_name)
                return
        super().mousePressEvent(event)

    def refresh(self):
        """Refresh map after project changes"""
        self._draw_map()


class MapViewWidget(QWidget):
    """Widget containing map view"""

    project_selected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("Project Locations Map")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #e74c3c;")
        layout.addWidget(title)

        # Info
        info = QLabel("Click on a red point to select a project")
        info.setStyleSheet("font-size: 10px; color: #666;")
        layout.addWidget(info)

        # Map
        self.map_view = MapView()
        self.map_view.project_clicked.connect(self.project_selected.emit)
        layout.addWidget(self.map_view)

    def refresh(self):
        """Refresh the map"""
        self.map_view.refresh()
