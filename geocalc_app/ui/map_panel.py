"""
GeoCalc Pro - Map Panel
Displays boring and CPT locations on an interactive Folium/Leaflet map
using Qt WebEngine.
"""
import os
import tempfile
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSplitter, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QComboBox, QToolBar, QDialog, QScrollArea, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings

from geocalc_app.core.database import get_project_borings, get_connection
from geocalc_app.core.mapping import build_project_map

logger = logging.getLogger(__name__)


class MapPanel(QWidget):
    boring_selected = pyqtSignal(dict)  # emitted when boring is clicked in table

    def __init__(self):
        super().__init__()
        self.project_id: Optional[int] = None
        self.borings: list[dict] = []
        self.cpt_soundings: list[dict] = []
        self._map_html_path: Optional[str] = None
        self._selected_boring: Optional[dict] = None
        self._build_ui()

    def set_project(self, project_id: int):
        self.project_id = project_id
        self.refresh()

    def refresh(self):
        if not self.project_id:
            return
        self._load_data()
        self._render_boring_table()
        self._render_map()

    def _load_data(self):
        self.borings = get_project_borings(self.project_id)
        # Load CPTs
        conn = get_connection()
        cpt_rows = conn.execute(
            "SELECT * FROM cpt_soundings WHERE project_id = ?", (self.project_id,)
        ).fetchall()
        self.cpt_soundings = [dict(r) for r in cpt_rows]
        # Add empty data_points
        for c in self.cpt_soundings:
            pts = conn.execute(
                "SELECT * FROM cpt_data WHERE sounding_id = ? ORDER BY depth",
                (c["id"],)
            ).fetchall()
            c["data_points"] = [dict(p) for p in pts]
        conn.close()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setObjectName("mapToolbar")

        lbl = QLabel("  🗺️  Site Map  ")
        lbl.setObjectName("toolbarTitle")
        toolbar.addWidget(lbl)
        toolbar.addSeparator()

        btn_refresh = QPushButton("⟳  Refresh")
        btn_refresh.clicked.connect(self.refresh)
        toolbar.addWidget(btn_refresh)

        btn_fit = QPushButton("⊞  Fit All")
        btn_fit.clicked.connect(self._fit_all)
        toolbar.addWidget(btn_fit)

        btn_export = QPushButton("📤  Export Map")
        btn_export.clicked.connect(self._export_map)
        toolbar.addWidget(btn_export)

        self.btn_view_log = QPushButton("📋  View Boring Log")
        self.btn_view_log.setToolTip("Select a boring in the list then click to view the graphical log")
        self.btn_view_log.clicked.connect(self._view_boring_log)
        toolbar.addWidget(self.btn_view_log)

        layout.addWidget(toolbar)

        # Main split: map | boring list
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Map (WebEngine) ────────────────────────────────────────────────
        self.map_view = QWebEngineView()
        self.map_view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self.map_view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, True
        )
        self._show_empty_map()
        splitter.addWidget(self.map_view)

        # ── Boring list (right panel) ─────────────────────────────────────
        right = QFrame()
        right.setObjectName("panelFrame")
        right.setMaximumWidth(320)
        right_layout = QVBoxLayout(right)

        right_layout.addWidget(QLabel("Boring Logs"))

        self.boring_count_lbl = QLabel("No borings loaded")
        self.boring_count_lbl.setStyleSheet("color:#666; font-size:12px;")
        right_layout.addWidget(self.boring_count_lbl)

        self.boring_tree = QTreeWidget()
        self.boring_tree.setHeaderLabels(["ID", "Depth", "Layers"])
        self.boring_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.boring_tree.itemClicked.connect(self._on_boring_click)
        right_layout.addWidget(self.boring_tree)

        right_layout.addWidget(QLabel("CPT Soundings"))
        self.cpt_tree = QTreeWidget()
        self.cpt_tree.setHeaderLabels(["ID", "Points"])
        self.cpt_tree.setMaximumHeight(150)
        right_layout.addWidget(self.cpt_tree)

        splitter.addWidget(right)
        splitter.setSizes([900, 280])
        layout.addWidget(splitter)

    def _show_empty_map(self):
        html = """
        <!DOCTYPE html><html><head>
        <style>body{margin:0;background:#1B3A5C;display:flex;align-items:center;
        justify-content:center;height:100vh;color:white;font-family:Arial,sans-serif;}
        .msg{text-align:center;opacity:0.7;}
        .msg h2{font-size:48px;margin:0;}
        .msg p{font-size:16px;margin-top:12px;}</style></head>
        <body><div class="msg">
        <h2>🗺️</h2>
        <p>Select a project and import a geotechnical report<br>to display boring locations on the map.</p>
        </div></body></html>"""
        self.map_view.setHtml(html)

    def _render_boring_table(self):
        self.boring_tree.clear()
        self.cpt_tree.clear()

        for b in self.borings:
            item = QTreeWidgetItem([
                b["boring_id"],
                f"{b.get('total_depth') or '?'} ft",
                str(len(b.get("layers", [])))
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, b)
            self.boring_tree.addTopLevelItem(item)

        for c in self.cpt_soundings:
            item = QTreeWidgetItem([
                c["cpt_id"],
                str(len(c.get("data_points", [])))
            ])
            self.cpt_tree.addTopLevelItem(item)

        total = len(self.borings)
        self.boring_count_lbl.setText(
            f"{total} boring{'s' if total != 1 else ''}, "
            f"{len(self.cpt_soundings)} CPT"
        )

    def _render_map(self):
        if not self.borings and not self.cpt_soundings:
            self._show_empty_map()
            return

        try:
            # Write to temp HTML file
            if self._map_html_path is None:
                tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
                self._map_html_path = tmp.name
                tmp.close()

            from geocalc_app.core.database import get_project
            project = get_project(self.project_id) if self.project_id else {}

            build_project_map(
                borings=self.borings,
                cpt_soundings=self.cpt_soundings,
                output_html=self._map_html_path,
                project_name=project.get("name", "Project") if project else "Project"
            )

            self.map_view.setUrl(QUrl.fromLocalFile(self._map_html_path))

        except Exception as e:
            logger.exception("Map rendering failed")
            self.map_view.setHtml(f"<h2>Map Error</h2><p>{e}</p>")

    def _on_boring_click(self, item: QTreeWidgetItem, column: int):
        boring_data = item.data(0, Qt.ItemDataRole.UserRole)
        if boring_data:
            self._selected_boring = boring_data
            self.boring_selected.emit(boring_data)

    def _fit_all(self):
        self._render_map()

    def _export_map(self):
        if not self._map_html_path:
            return
        from PyQt6.QtWidgets import QFileDialog
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export Map", "site_map.html", "HTML Files (*.html)"
        )
        if dest:
            import shutil
            shutil.copy(self._map_html_path, dest)

    def _view_boring_log(self):
        if not self._selected_boring:
            QMessageBox.information(self, "No Boring Selected",
                                    "Click a boring in the list on the right first.")
            return
        try:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            from geocalc_app.core.mapping import build_boring_log
            build_boring_log(self._selected_boring, tmp.name)
            dialog = BoringLogDialog(
                self._selected_boring.get("boring_id", "Boring Log"),
                tmp.name, self
            )
            dialog.exec()
        except Exception as e:
            logger.exception("Boring log viewer failed")
            QMessageBox.critical(self, "Error", f"Failed to generate boring log:\n{e}")


class BoringLogDialog(QDialog):
    """Modal dialog displaying the graphical boring log image."""

    def __init__(self, boring_id: str, image_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Boring Log — {boring_id}")
        self.setMinimumSize(950, 720)
        self.resize(1050, 820)

        layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        from PyQt6.QtGui import QPixmap
        lbl = QLabel()
        pixmap = QPixmap(image_path)
        lbl.setPixmap(pixmap)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(lbl)
        layout.addWidget(scroll)

        btn_row = QHBoxLayout()
        btn_export = QPushButton("📤  Save PNG...")
        btn_export.clicked.connect(lambda: self._export(image_path))
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_export)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _export(self, src_path: str):
        from PyQt6.QtWidgets import QFileDialog
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save Boring Log", "boring_log.png", "PNG Images (*.png)"
        )
        if dest:
            import shutil
            shutil.copy(src_path, dest)
