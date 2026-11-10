"""
GeoCalc Pro - Main Window
PyQt6 main application window with sidebar navigation.
"""
import os
import sys
import json
import logging
import tempfile
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QPushButton, QLabel, QFrame, QSizePolicy, QMessageBox,
    QFileDialog, QStatusBar, QToolBar, QSplitter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QSettings
from PyQt6.QtGui import QIcon, QFont, QAction, QPixmap

from geocalc_app.ui.project_panel import ProjectPanel
from geocalc_app.ui.report_panel import ReportPanel
from geocalc_app.ui.map_panel import MapPanel
from geocalc_app.ui.fence_panel import FenceDiagramPanel
from geocalc_app.ui.settings_dialog import SettingsDialog
from geocalc_app.core.database import initialize_database

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("GeoCalc", "GeoCalcPro")
        self.current_project_id: Optional[int] = None

        # Initialize DB
        initialize_database()

        self._setup_window()
        self._build_ui()
        self._apply_connections()

        # Restore last project
        last_pid = self.settings.value("last_project_id", type=int)
        if last_pid:
            self._switch_project(last_pid)

    def _setup_window(self):
        self.setWindowTitle("GeoCalc Pro — Geotechnical Engineering Platform")
        self.resize(1400, 900)
        self.setMinimumSize(1100, 700)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────────
        self.sidebar = self._build_sidebar()
        root_layout.addWidget(self.sidebar)

        # ── Main content stack ───────────────────────────────────────────────
        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack, 1)

        # Panels
        self.project_panel = ProjectPanel()
        self.report_panel = ReportPanel()
        self.map_panel = MapPanel()
        self.fence_panel = FenceDiagramPanel()

        # Placeholder panels for future modules
        self.calc_panel = _PlaceholderPanel("Engineering Calculations", "📐",
                                            "Deep foundation, ground improvement,\nand earth retention calculations\ncoming in the next module.")
        self.arduino_panel = _PlaceholderPanel("Instrumentation", "📡",
                                               "Arduino sensor data acquisition,\nreal-time monitoring and logging\ncoming soon.")
        self.steel_panel = _PlaceholderPanel("Steel Design", "🏗️",
                                             "Structural steel design calculations\nper AISC specifications\ncoming soon.")

        for panel in [self.project_panel, self.report_panel, self.map_panel,
                      self.fence_panel, self.calc_panel, self.arduino_panel, self.steel_panel]:
            self.stack.addWidget(panel)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready — Select or create a project to begin")

        # Menu bar
        self._build_menu()

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Logo / Title
        header = QLabel()
        header.setObjectName("sidebarHeader")
        header.setText("GeoCalc\nPro")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setFixedHeight(80)
        layout.addWidget(header)

        # Section: Project
        layout.addWidget(self._sidebar_section("PROJECT"))
        self.btn_projects = self._nav_button("📁  Projects", 0)
        self.btn_reports = self._nav_button("📄  Import Report", 1)
        layout.addWidget(self.btn_projects)
        layout.addWidget(self.btn_reports)

        # Section: View
        layout.addWidget(self._sidebar_section("VISUALIZE"))
        self.btn_map = self._nav_button("🗺️  Site Map", 2)
        self.btn_fence = self._nav_button("📊  Fence Diagram", 3)
        layout.addWidget(self.btn_map)
        layout.addWidget(self.btn_fence)

        # Section: Calculate
        layout.addWidget(self._sidebar_section("CALCULATE"))
        self.btn_calcs = self._nav_button("📐  Geotech Calcs", 4)
        layout.addWidget(self.btn_calcs)

        # Section: Future
        layout.addWidget(self._sidebar_section("COMING SOON"))
        self.btn_arduino = self._nav_button("📡  Instrumentation", 5)
        self.btn_steel = self._nav_button("🏗️  Steel Design", 6)
        layout.addWidget(self.btn_arduino)
        layout.addWidget(self.btn_steel)

        layout.addStretch()

        # Bottom: Settings
        btn_settings = QPushButton("⚙️  Settings")
        btn_settings.setObjectName("settingsButton")
        btn_settings.clicked.connect(self._open_settings)
        layout.addWidget(btn_settings)

        # Current project label
        self.project_label = QLabel("No project selected")
        self.project_label.setObjectName("currentProjectLabel")
        self.project_label.setWordWrap(True)
        self.project_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.project_label)

        self._nav_buttons = [
            self.btn_projects, self.btn_reports, self.btn_map,
            self.btn_fence, self.btn_calcs, self.btn_arduino, self.btn_steel
        ]

        return sidebar

    def _sidebar_section(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("sidebarSection")
        return lbl

    def _nav_button(self, text: str, index: int) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("navButton")
        btn.setCheckable(True)
        btn.clicked.connect(lambda checked, i=index: self._navigate(i))
        return btn

    def _build_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        act_new = QAction("New Project", self)
        act_new.setShortcut("Ctrl+N")
        act_new.triggered.connect(lambda: (self._navigate(0), self.project_panel.create_new_project()))
        file_menu.addAction(act_new)

        act_import = QAction("Import Report PDF...", self)
        act_import.setShortcut("Ctrl+O")
        act_import.triggered.connect(lambda: self._navigate(1))
        file_menu.addAction(act_import)

        file_menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        view_menu = menubar.addMenu("&View")
        act_map = QAction("Site Map", self)
        act_map.triggered.connect(lambda: self._navigate(2))
        view_menu.addAction(act_map)
        act_fence = QAction("Fence Diagram", self)
        act_fence.triggered.connect(lambda: self._navigate(3))
        view_menu.addAction(act_fence)

        help_menu = menubar.addMenu("&Help")
        act_about = QAction("About GeoCalc Pro", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _apply_connections(self):
        self.project_panel.project_selected.connect(self._switch_project)
        self.report_panel.report_processed.connect(self._on_report_processed)
        self.map_panel.boring_selected.connect(self.fence_panel.add_boring_to_selection)

    def _navigate(self, index: int):
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)
        self.stack.setCurrentIndex(index)

    def _switch_project(self, project_id: int):
        self.current_project_id = project_id
        self.settings.setValue("last_project_id", project_id)

        # Propagate to all panels
        from geocalc_app.core.database import get_project
        project = get_project(project_id)
        if project:
            self.project_label.setText(f"📁 {project['name']}")
            self.status_bar.showMessage(f"Project: {project['name']}")

        self.report_panel.set_project(project_id)
        self.map_panel.set_project(project_id)
        self.fence_panel.set_project(project_id)

    def _on_report_processed(self, report_id: int):
        """After a report is processed, refresh map."""
        if self.current_project_id:
            self.map_panel.refresh()
            self.fence_panel.refresh()
        self.status_bar.showMessage("Report imported successfully. Map updated.")

    def _open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()

    def _show_about(self):
        QMessageBox.about(
            self, "About GeoCalc Pro",
            "<h2>GeoCalc Pro v1.0</h2>"
            "<p>Geotechnical Engineering Analysis Platform</p>"
            "<p>Module 1: Boring Log Import & Site Mapping</p>"
            "<hr>"
            "<p>Built with PyQt6, Folium, pdfplumber, and Claude AI</p>"
        )

    def closeEvent(self, event):
        self.settings.setValue("window_geometry", self.saveGeometry())
        super().closeEvent(event)


class _PlaceholderPanel(QWidget):
    """Simple placeholder for future modules."""
    def __init__(self, title: str, icon: str, description: str):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        emoji = QLabel(icon)
        emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        emoji.setStyleSheet("font-size: 64px;")

        lbl_title = QLabel(title)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1B3A5C;")

        lbl_desc = QLabel(description)
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_desc.setStyleSheet("font-size: 14px; color: #666; margin-top: 12px;")

        layout.addWidget(emoji)
        layout.addWidget(lbl_title)
        layout.addWidget(lbl_desc)
