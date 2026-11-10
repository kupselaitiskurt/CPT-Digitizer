"""
GeoCalc Pro - Fence Diagram Panel
Select borings, set parameters, and generate 2D cross-section fence diagrams.
"""
import os
import tempfile
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSplitter, QListWidget, QListWidgetItem, QCheckBox,
    QDoubleSpinBox, QSpinBox, QSlider, QGroupBox, QFormLayout,
    QScrollArea, QFileDialog, QMessageBox, QLineEdit, QToolBar
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QImage

from geocalc_app.core.database import get_project_borings, get_connection
from geocalc_app.core.mapping import build_fence_diagram

logger = logging.getLogger(__name__)


class FenceDiagramPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.project_id: Optional[int] = None
        self.all_borings: list[dict] = []
        self._diagram_path: Optional[str] = None
        self._build_ui()

    def set_project(self, project_id: int):
        self.project_id = project_id
        self.refresh()

    def refresh(self):
        if not self.project_id:
            return
        self.all_borings = get_project_borings(self.project_id)
        self._populate_boring_list()

    def add_boring_to_selection(self, boring_data: dict):
        """Called when a boring is clicked in the Map panel."""
        bid = boring_data.get("boring_id")
        for i in range(self.boring_list.count()):
            item = self.boring_list.item(i)
            if item.text() == bid:
                item.setCheckState(Qt.CheckState.Checked)
                break

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setObjectName("mapToolbar")
        lbl = QLabel("  📊  Fence Diagram (Cross-Section)  ")
        lbl.setObjectName("toolbarTitle")
        toolbar.addWidget(lbl)
        toolbar.addSeparator()
        btn_gen = QPushButton("⚡  Generate Diagram")
        btn_gen.setObjectName("primaryButton")
        btn_gen.clicked.connect(self._generate)
        toolbar.addWidget(btn_gen)
        btn_export = QPushButton("📤  Export PNG")
        btn_export.clicked.connect(self._export)
        toolbar.addWidget(btn_export)
        btn_select_all = QPushButton("☑  Select All")
        btn_select_all.clicked.connect(self._select_all)
        toolbar.addWidget(btn_select_all)
        btn_clear = QPushButton("☐  Clear")
        btn_clear.clicked.connect(self._clear_selection)
        toolbar.addWidget(btn_clear)
        layout.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: boring selection + settings ────────────────────────────
        left = QFrame()
        left.setObjectName("panelFrame")
        left.setMaximumWidth(300)
        left_layout = QVBoxLayout(left)

        left_layout.addWidget(QLabel("Select Borings for Section:"))

        self.boring_list = QListWidget()
        self.boring_list.setObjectName("projectList")
        left_layout.addWidget(self.boring_list)

        # Diagram title
        title_group = QGroupBox("Diagram Settings")
        title_form = QFormLayout(title_group)

        self.title_edit = QLineEdit("Cross-Section A–A'")
        title_form.addRow("Title:", self.title_edit)

        self.ve_spin = QDoubleSpinBox()
        self.ve_spin.setRange(1.0, 50.0)
        self.ve_spin.setValue(1.0)
        self.ve_spin.setSuffix("x")
        self.ve_spin.setToolTip("Vertical exaggeration factor")
        title_form.addRow("Vert. Exaggeration:", self.ve_spin)

        self.gwt_check = QCheckBox("Show Water Table")
        self.gwt_check.setChecked(True)
        title_form.addRow(self.gwt_check)

        left_layout.addWidget(title_group)
        left_layout.addStretch()

        splitter.addWidget(left)

        # ── Right: diagram image ──────────────────────────────────────────
        right = QFrame()
        right.setObjectName("panelFrame")
        right_layout = QVBoxLayout(right)

        # Scroll area for diagram
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.diagram_label = QLabel()
        self.diagram_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.diagram_label.setText(
            "<div style='text-align:center; color:#999; font-size:48px;'>📊</div>"
            "<div style='text-align:center; color:#999; margin-top:16px;'>"
            "Select borings from the left panel<br>and click Generate Diagram</div>"
        )
        scroll.setWidget(self.diagram_label)
        right_layout.addWidget(scroll)

        splitter.addWidget(right)
        splitter.setSizes([280, 900])
        layout.addWidget(splitter)

    def _populate_boring_list(self):
        self.boring_list.clear()
        for b in self.all_borings:
            item = QListWidgetItem(b["boring_id"])
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, b)
            item.setToolTip(
                f"Depth: {b.get('total_depth') or '?'} ft\n"
                f"Layers: {len(b.get('layers', []))}\n"
                f"Coord: {b.get('latitude') or 'No coords'}"
            )
            self.boring_list.addItem(item)

    def _get_selected_borings(self) -> list[dict]:
        selected = []
        for i in range(self.boring_list.count()):
            item = self.boring_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))
        return selected

    def _select_all(self):
        for i in range(self.boring_list.count()):
            self.boring_list.item(i).setCheckState(Qt.CheckState.Checked)

    def _clear_selection(self):
        for i in range(self.boring_list.count()):
            self.boring_list.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _generate(self):
        selected = self._get_selected_borings()
        if not selected:
            QMessageBox.information(self, "No Selection",
                                    "Please check at least one boring from the list.")
            return
        if len(selected) < 2:
            QMessageBox.information(self, "Need More",
                                    "Select at least 2 borings for a cross-section.")
            return

        try:
            if self._diagram_path is None:
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                self._diagram_path = tmp.name
                tmp.close()

            build_fence_diagram(
                borings=selected,
                output_path=self._diagram_path,
                title=self.title_edit.text() or "Cross-Section",
                vertical_exaggeration=self.ve_spin.value(),
                show_water_table=self.gwt_check.isChecked()
            )

            # Display in label
            pixmap = QPixmap(self._diagram_path)
            if not pixmap.isNull():
                # Scale to fit while preserving aspect ratio
                scaled = pixmap.scaledToWidth(
                    min(pixmap.width(), 1600),
                    Qt.TransformationMode.SmoothTransformation
                )
                self.diagram_label.setPixmap(scaled)
                self.diagram_label.adjustSize()

        except Exception as e:
            logger.exception("Fence diagram generation failed")
            QMessageBox.critical(self, "Error", f"Failed to generate diagram:\n{e}")

    def _export(self):
        if not self._diagram_path or not os.path.exists(self._diagram_path):
            QMessageBox.information(self, "No Diagram", "Generate a diagram first.")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export Fence Diagram", "fence_diagram.png",
            "PNG Images (*.png);;PDF Files (*.pdf)"
        )
        if dest:
            import shutil
            shutil.copy(self._diagram_path, dest)
            QMessageBox.information(self, "Exported", f"Diagram saved to:\n{dest}")
