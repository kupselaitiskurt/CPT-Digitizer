#!/usr/bin/env python3
"""
CPT Graph Digitizer — Standalone Application
==============================================
Extracts tip resistance (qc), sleeve friction (fs), and pore water pressure (u2)
from scanned CPT graph images or screen captures.

USAGE
-----
  python cpt_digitizer.py

WORKFLOW
--------
1. Load a CPT graph image or capture a screen region
2. Calibrate X-axis (measurement value) with 2 reference points
3. Calibrate Y-axis (depth) with 2 reference points
4. Pick the curve colour by clicking on the plotted line
5. Extract data at a specified depth interval
6. Export to CSV or Excel

Each channel (qc, fs, u2) is calibrated independently; extraction produces
a single table aligned to a common depth column.

Dependencies (all in requirements.txt):
  PyQt6, numpy, pandas, matplotlib, Pillow, openpyxl
"""

import sys
import base64
import io
import os
import re
from dataclasses import dataclass
from typing import Optional, List, Tuple

import numpy as np
import pandas as pd
from openpyxl.chart import ScatterChart, Reference, Series
from openpyxl.utils import get_column_letter

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QGraphicsView, QGraphicsScene, QLabel, QPushButton,
    QLineEdit, QSlider, QFrame, QScrollArea, QFileDialog, QMessageBox,
    QSplitter, QStatusBar, QGroupBox, QGridLayout, QDialog, QSizePolicy,
    QRubberBand, QComboBox, QTreeWidget, QTreeWidgetItem, QTableWidget,
    QTableWidgetItem, QSpinBox, QDoubleSpinBox, QListWidget, QCheckBox,
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QRect, QSize, pyqtSignal
from PyQt6.QtGui import (
    QPixmap, QColor, QPainter, QPen, QBrush, QImage, QCursor,
    QAction, QFont, QKeySequence,
)

try:
    from PIL import Image, ImageGrab, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import matplotlib
    matplotlib.use("Agg")          # headless — we render to bytes and show in Qt
    import matplotlib.pyplot as plt
    MPL_AVAILABLE = True
except ImportError:
    MPL_AVAILABLE = False

try:
    from project_ui import ProjectManagerUI
    from project_manager import ProjectManager, CPTData
    PROJECT_UI_AVAILABLE = True
except ImportError:
    PROJECT_UI_AVAILABLE = False
    ProjectManager = None
    CPTData = None


# ─────────────────────────────────────────────────────────────────────────────
#  Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AxisCal:
    """Two-point linear calibration for one image axis."""
    p1: Optional[float] = None   # pixel coordinate of known point 1
    v1: Optional[float] = None   # real-world value at p1
    p2: Optional[float] = None   # pixel coordinate of known point 2
    v2: Optional[float] = None   # real-world value at p2

    @property
    def ready(self) -> bool:
        return all(x is not None for x in (self.p1, self.v1, self.p2, self.v2))

    def to_value(self, pixel: float) -> Optional[float]:
        if not self.ready or self.p2 == self.p1:
            return None
        return self.v1 + (pixel - self.p1) * (self.v2 - self.v1) / (self.p2 - self.p1)

    def to_pixel(self, value: float) -> Optional[float]:
        if not self.ready or self.v2 == self.v1:
            return None
        return self.p1 + (value - self.v1) * (self.p2 - self.p1) / (self.v2 - self.v1)


# ─────────────────────────────────────────────────────────────────────────────
#  Screen-capture overlay
# ─────────────────────────────────────────────────────────────────────────────

class CaptureOverlay(QDialog):
    """Full-screen semi-transparent window for rubber-band region selection."""

    region_selected = pyqtSignal(QRect)

    def __init__(self, screen_pixmap: QPixmap, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self._pixmap = screen_pixmap
        self._origin = None
        self._current = None

    def paintEvent(self, _event):
        painter = QPainter(self)
        # Dim background
        painter.drawPixmap(0, 0, self._pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        if self._origin and self._current:
            rect = QRect(self._origin, self._current).normalized()
            # Clear selection area
            painter.drawPixmap(rect, self._pixmap, rect)
            pen = QPen(QColor("#e74c3c"), 2)
            painter.setPen(pen)
            painter.drawRect(rect)
        # Instructions
        font = QFont(); font.setPointSize(13); font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("yellow"))
        painter.drawText(14, 30, "Drag to select the graph region    |    ESC to cancel")

    def mousePressEvent(self, event):
        self._origin = event.pos()
        self._current = event.pos()
        self.update()

    def mouseMoveEvent(self, event):
        self._current = event.pos()
        self.update()

    def mouseReleaseEvent(self, event):
        if self._origin:
            rect = QRect(self._origin, event.pos()).normalized()
            self.accept()
            if rect.width() > 20 and rect.height() > 20:
                self.region_selected.emit(rect)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()


# ─────────────────────────────────────────────────────────────────────────────
#  Custom image view
# ─────────────────────────────────────────────────────────────────────────────

class ImageView(QGraphicsView):
    """Zoomable/pannable image view that emits scene-space clicks."""

    clicked = pyqtSignal(QPointF)

    def __init__(self):
        super().__init__()
        scene = QGraphicsScene(self)
        self.setScene(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setStyleSheet("background: #1e1e1e; border: none;")
        self._intercept_click = False
        self._pixmap_item = None
        self._overlay_items = []

    def set_pixmap(self, pixmap: QPixmap):
        self.scene().clear()
        self._overlay_items.clear()
        self._pixmap_item = self.scene().addPixmap(pixmap)
        self.setSceneRect(QRectF(pixmap.rect()))
        self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def clear_image(self):
        self.scene().clear()
        self._overlay_items.clear()
        self._pixmap_item = None

    def set_capture_mode(self, active: bool):
        self._intercept_click = active
        if active:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.unsetCursor()

    def set_pan_mode(self):
        """Enable pan mode with hand cursor."""
        self._intercept_click = False
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))

    def add_marker(self, x: float, y: float, color: str, label: str):
        pen = QPen(QColor(color), 2)
        r = 6
        ellipse = self.scene().addEllipse(x - r, y - r, r * 2, r * 2, pen)
        h_line = self.scene().addLine(x - r - 5, y, x + r + 5, y, pen)
        v_line = self.scene().addLine(x, y - r - 5, x, y + r + 5, pen)
        text = self.scene().addText(label, QFont("Arial", 8))
        text.setDefaultTextColor(QColor(color))
        text.setPos(x + r + 3, y - 10)
        self._overlay_items.extend([ellipse, h_line, v_line, text])

    def add_dot(self, x: float, y: float):
        brush = QBrush(QColor("#ff8c00"))
        self._overlay_items.append(
            self.scene().addEllipse(x - 2, y - 2, 4, 4, QPen(Qt.PenStyle.NoPen), brush)
        )

    def clear_overlays(self):
        for item in self._overlay_items:
            self.scene().removeItem(item)
        self._overlay_items.clear()

    def mousePressEvent(self, event):
        if self._intercept_click and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.mapToScene(event.pos()))
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 0.87
        self.scale(factor, factor)

    def fit(self):
        if self._pixmap_item:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)


# ─────────────────────────────────────────────────────────────────────────────
#  Channel tab (one per CPT measurement)
# ─────────────────────────────────────────────────────────────────────────────

MIN_INTERVAL_FT = 0.1  # finest depth interval allowed (the standard)
FT_PER_M = 3.28084


def _convert_depth(value: float, from_units: str, to_units: str) -> float:
    """Convert a depth value between m and ft."""
    if from_units == to_units:
        return value
    if from_units == "m" and to_units == "ft":
        return value * FT_PER_M
    if from_units == "ft" and to_units == "m":
        return value / FT_PER_M
    return value


class ChannelTab(QWidget):
    """One tab handling image loading, calibration, and data extraction."""

    interval_changed = pyqtSignal()  # emitted when the user edits the depth interval

    _MODES = {
        "idle":       "",
        "cal_x1":     "▶  Click the first X-AXIS reference point on the image",
        "cal_x2":     "▶  Click the second X-AXIS reference point on the image",
        "cal_y1":     "▶  Click the first Y-AXIS (depth) reference point",
        "cal_y2":     "▶  Click the second Y-AXIS (depth) reference point",
        "pick_color": "▶  Click directly ON the plotted curve to sample its colour",
        "pan":        "🖐  Drag the image to pan (left-click and move mouse)",
    }

    def __init__(self, name: str, default_units: str, mpl_color: str):
        super().__init__()
        self.name = name
        self.units = default_units
        self.mpl_color = mpl_color
        self.depth_units = "ft"  # Default to feet
        self._syncing = False    # True while the interval is set by code (no re-broadcast)

        # Unit options by channel type
        self.unit_options = {
            "qc": ["MPa", "ksf", "tsf", "psi", "kPa"],
            "fs": ["kPa", "ksf", "tsf", "psi", "psf"],
            "u2": ["kPa", "psi", "psf"],
        }.get(name, ["MPa", "kPa", "psi"])

        # State
        self._pil_image: Optional[Image.Image] = None
        self._img_arr: Optional[np.ndarray] = None
        self._mode = "idle"
        self.x_cal = AxisCal()
        self.y_cal = AxisCal()
        self.curve_color: Optional[Tuple[int, int, int]] = None
        self.extracted: List[Tuple[float, float]] = []   # (depth, value)
        self._markers: List[Tuple[float, float, str, str]] = []  # (px,py,color,label)

        self._build_ui()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        # ── Left: image viewer ──
        left_wrap = QWidget()
        lv = QVBoxLayout(left_wrap)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(2)

        self.view = ImageView()
        self.view.clicked.connect(self._on_view_click)
        lv.addWidget(self.view)

        self.coord_label = QLabel("Load an image to begin")
        self.coord_label.setStyleSheet("font-size: 11px; padding: 2px; "
                                        "background: #2b2b2b; color: #aaaaaa;")
        lv.addWidget(self.coord_label)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 11px; padding: 2px; "
                                         "background: #2b2b2b; color: #e0e0e0;")
        lv.addWidget(self.status_label)

        splitter.addWidget(left_wrap)

        # ── Right: controls (scrollable, resizable) ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(250)  # Minimum width instead of fixed
        scroll.setStyleSheet("QScrollArea { border: none; }")

        ctrl_widget = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_widget)
        ctrl_layout.setContentsMargins(8, 8, 8, 8)
        ctrl_layout.setSpacing(6)
        scroll.setWidget(ctrl_widget)
        splitter.addWidget(scroll)

        # Configure splitter collapsibility after widgets are added
        splitter.setCollapsible(0, False)  # Don't collapse image viewer
        splitter.setCollapsible(1, True)   # Allow collapsing control panel
        splitter.setSizes([1200, 350])  # Image viewer : Control panel ratio
        splitter.setStretchFactor(0, 1)  # Image viewer gets extra space
        splitter.setStretchFactor(1, 0)  # Control panel stays fixed width

        p = ctrl_layout

        def section(title: str) -> QGroupBox:
            g = QGroupBox(title)
            g.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 6px; }"
                            "QGroupBox::title { subcontrol-origin: margin; left: 8px; }")
            return g

        def btn(label: str, slot) -> QPushButton:
            b = QPushButton(label)
            b.clicked.connect(slot)
            return b

        # ── Image group ──
        img_grp = section("Image")
        ig = QVBoxLayout(img_grp)
        ig.addWidget(btn("Load Image File…", self.load_image))
        ig.addWidget(btn("Capture Screen Region", self.capture_region))
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(btn("Zoom +", lambda: self.view.scale(1.25, 1.25)))
        zoom_row.addWidget(btn("Zoom −", lambda: self.view.scale(0.8, 0.8)))
        zoom_row.addWidget(btn("Fit", self.view.fit))
        ig.addLayout(zoom_row)

        # Pan button
        self.pan_btn = btn("🖐 Pan (drag to move)", lambda: self._set_mode("pan"))
        ig.addWidget(self.pan_btn)

        p.addWidget(img_grp)

        # ── Units selector ──
        units_row = QHBoxLayout()
        units_row.addWidget(QLabel("X-Axis Units:"))
        self.units_combo = QComboBox()
        self.units_combo.addItems(self.unit_options)
        self.units_combo.setCurrentText(self.units)
        self.units_combo.currentTextChanged.connect(self._on_units_changed)
        units_row.addWidget(self.units_combo)
        units_row.addStretch()
        p.addLayout(units_row)

        # ── Depth units selector ──
        depth_row = QHBoxLayout()
        depth_row.addWidget(QLabel("Depth Units:"))
        self.depth_units_combo = QComboBox()
        self.depth_units_combo.addItems(["m", "ft"])
        self.depth_units_combo.setCurrentText("ft")
        self.depth_units_combo.currentTextChanged.connect(self._on_depth_units_changed)
        depth_row.addWidget(self.depth_units_combo)
        depth_row.addStretch()
        p.addLayout(depth_row)

        # ── X-axis calibration ──
        self.x_grp = section(f"X-Axis Calibration  ({self.units})")
        xg = QGridLayout(self.x_grp)
        note = QLabel("Enter a known value → click button → click that location on image.\n(Order doesn't matter)")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 10px; font-weight: normal;")
        xg.addWidget(note, 0, 0, 1, 3)

        self.x_min_edit = QLineEdit("0")
        self.x_max_edit = QLineEdit("10")
        self.x1_ind = QLabel("○"); self.x1_ind.setStyleSheet("color: #e74c3c; font-size: 14px;")
        self.x2_ind = QLabel("○"); self.x2_ind.setStyleSheet("color: #e74c3c; font-size: 14px;")

        self.x1_btn = btn("Set X-Point 1 →", lambda: self._set_mode("cal_x1"))
        xg.addWidget(self.x1_btn, 1, 0)
        xg.addWidget(self.x_min_edit, 1, 1)
        xg.addWidget(self.x1_ind, 1, 2)
        self.x2_btn = btn("Set X-Point 2 →", lambda: self._set_mode("cal_x2"))
        xg.addWidget(self.x2_btn, 2, 0)
        xg.addWidget(self.x_max_edit, 2, 1)
        xg.addWidget(self.x2_ind, 2, 2)

        # Reset X calibration button
        reset_x_btn = btn("Reset X Calibration", self._reset_x_cal)
        xg.addWidget(reset_x_btn, 3, 0, 1, 3)

        p.addWidget(self.x_grp)

        # ── Y-axis calibration ──
        self.y_grp = section(f"Y-Axis Calibration  (Depth, {self.depth_units})")
        yg = QGridLayout(self.y_grp)
        note2 = QLabel("Enter a known depth → click button → click that location on image.\n(Order doesn't matter)")
        note2.setStyleSheet("color: gray; font-size: 10px; font-weight: normal;")
        yg.addWidget(note2, 0, 0, 1, 3)

        self.y_min_edit = QLineEdit("0")
        self.y_max_edit = QLineEdit("20")
        self.y1_ind = QLabel("○"); self.y1_ind.setStyleSheet("color: #e74c3c; font-size: 14px;")
        self.y2_ind = QLabel("○"); self.y2_ind.setStyleSheet("color: #e74c3c; font-size: 14px;")

        self.y1_btn = btn("Set Y-Point 1 →", lambda: self._set_mode("cal_y1"))
        yg.addWidget(self.y1_btn, 1, 0)
        yg.addWidget(self.y_min_edit, 1, 1)
        yg.addWidget(self.y1_ind, 1, 2)
        self.y2_btn = btn("Set Y-Point 2 →", lambda: self._set_mode("cal_y2"))
        yg.addWidget(self.y2_btn, 2, 0)
        yg.addWidget(self.y_max_edit, 2, 1)
        yg.addWidget(self.y2_ind, 2, 2)

        # Reset Y calibration button
        reset_y_btn = btn("Reset Y Calibration", self._reset_y_cal)
        yg.addWidget(reset_y_btn, 3, 0, 1, 3)

        p.addWidget(self.y_grp)

        # ── Curve detection ──
        cd_grp = section("Curve Detection")
        cg = QVBoxLayout(cd_grp)
        cg.addWidget(btn("Pick Curve Colour  (click on curve)", lambda: self._set_mode("pick_color")))

        self.swatch = QLabel()
        self.swatch.setFixedHeight(26)
        self.swatch.setStyleSheet("background: #888888; border: 1px solid #555;")
        cg.addWidget(self.swatch)
        self.color_lbl = QLabel("No colour selected yet")
        self.color_lbl.setStyleSheet("font-size: 10px;")
        cg.addWidget(self.color_lbl)

        tol_row = QHBoxLayout()
        tol_row.addWidget(QLabel("Tolerance:"))
        self.tol_slider = QSlider(Qt.Orientation.Horizontal)
        self.tol_slider.setRange(1, 150)
        self.tol_slider.setValue(30)
        self.tol_lbl = QLabel("30")
        self.tol_slider.valueChanged.connect(lambda v: self.tol_lbl.setText(str(v)))
        tol_row.addWidget(self.tol_slider)
        tol_row.addWidget(self.tol_lbl)
        cg.addLayout(tol_row)
        cg.addWidget(btn("Show Colour Mask Preview", self._show_mask))
        p.addWidget(cd_grp)

        # ── Extraction ──
        ex_grp = section("Data Extraction")
        eg = QVBoxLayout(ex_grp)
        di_row = QHBoxLayout()
        self.di_lbl = QLabel(f"Depth interval ({self.depth_units}):")
        di_row.addWidget(self.di_lbl)
        self.di_spin = QDoubleSpinBox()
        self.di_spin.setRange(self._min_interval(), 10.0)  # Floor 0.1 ft, Max 10
        self.di_spin.setValue(0.1)  # Standard: 0.1 ft
        self.di_spin.setSingleStep(0.005)  # Step by 0.005
        self.di_spin.setDecimals(6)  # Enough precision that m <-> ft conversion does not drift
        self.di_spin.setFixedWidth(80)
        di_row.addWidget(self.di_spin)
        di_row.addStretch()
        eg.addLayout(di_row)
        self.per_px_cb = QCheckBox("Every pixel row (finest possible)")
        self.per_px_cb.toggled.connect(self._on_per_pixel_toggled)
        self.di_spin.valueChanged.connect(self._on_interval_edited)
        self.per_px_cb.toggled.connect(self._on_interval_edited)
        eg.addWidget(self.per_px_cb)
        self.per_px_lbl = QLabel("")
        self.per_px_lbl.setStyleSheet("color: #888; font-size: 11px;")
        eg.addWidget(self.per_px_lbl)
        eg.addWidget(btn("Extract Data", self.extract_data))
        eg.addWidget(btn("Preview This Channel", self.preview))
        eg.addWidget(btn("Clear All", self.clear))
        self.extract_lbl = QLabel("")
        self.extract_lbl.setWordWrap(True)
        self.extract_lbl.setStyleSheet("color: #27ae60; font-size: 11px;")
        eg.addWidget(self.extract_lbl)
        p.addWidget(ex_grp)

        p.addStretch()

    # ── Image management ─────────────────────────────────────────────────────

    def load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, f"Open {self.name} graph image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.tif);;All files (*)"
        )
        if path:
            if PIL_AVAILABLE:
                img = Image.open(path).convert("RGB")
            else:
                img = None
            self._set_image(img, QPixmap(path), os.path.basename(path))

    def capture_region(self):
        if not PIL_AVAILABLE:
            QMessageBox.warning(self, "Missing dependency",
                                "Pillow is required for screen capture.\n"
                                "Run:  pip install Pillow")
            return
        win = self.window()
        win.hide()
        QApplication.processEvents()

        try:
            screen = QApplication.primaryScreen()
            full_pix = screen.grabWindow(0)
            # Also grab via PIL for actual pixel data
            full_pil = ImageGrab.grab()
        except Exception as e:
            win.show()
            QMessageBox.critical(self, "Capture error", str(e))
            return

        overlay = CaptureOverlay(full_pix, self)

        def on_region(rect: QRect):
            win.show()
            dpr = screen.devicePixelRatio()
            x0 = int(rect.x() * dpr)
            y0 = int(rect.y() * dpr)
            x1 = int((rect.x() + rect.width()) * dpr)
            y1 = int((rect.y() + rect.height()) * dpr)
            # Guard against bounds
            pw, ph = full_pil.size
            x0 = max(0, min(x0, pw)); x1 = max(0, min(x1, pw))
            y0 = max(0, min(y0, ph)); y1 = max(0, min(y1, ph))
            if x1 > x0 and y1 > y0:
                cropped = full_pil.crop((x0, y0, x1, y1)).convert("RGB")
                qpix = _pil_to_qpixmap(cropped)
                self._set_image(cropped, qpix, f"Screen capture {cropped.size[0]}×{cropped.size[1]}")

        overlay.region_selected.connect(on_region)
        overlay.rejected.connect(win.show)
        overlay.exec()

    def _set_image(self, pil_img: Optional[Image.Image], qpix: QPixmap, label: str):
        self._pil_image = pil_img
        self._img_arr = np.array(pil_img) if pil_img else None
        self.x_cal = AxisCal(); self.y_cal = AxisCal()
        self.curve_color = None
        self.extracted.clear(); self._markers.clear()
        # Reset indicators
        for ind in (self.x1_ind, self.x2_ind, self.y1_ind, self.y2_ind):
            ind.setText("○"); ind.setStyleSheet("color: #e74c3c; font-size: 14px;")
        self.swatch.setStyleSheet("background: #888888; border: 1px solid #555;")
        self.color_lbl.setText("No colour selected yet")
        self.extract_lbl.setText("")
        self.view.set_pixmap(qpix)
        self._set_status(f"Loaded: {label}")

    def _set_status(self, msg: str):
        self.status_label.setText(msg)
        # Bubble up to main window status bar if possible
        win = self.window()
        if hasattr(win, "statusBar"):
            win.statusBar().showMessage(msg, 5000)

    def _on_units_changed(self, new_units: str):
        self.units = new_units
        self.x_grp.setTitle(f"X-Axis Calibration  ({new_units})")

    def _min_interval(self) -> float:
        """The 0.1 ft floor expressed in this tab's depth units."""
        return _convert_depth(MIN_INTERVAL_FT, "ft", self.depth_units)

    def _on_interval_edited(self, *_):
        if not self._syncing:
            self.interval_changed.emit()

    def set_interval(self, value: float, units: str, per_pixel: bool):
        """Set the interval from another tab (no re-broadcast)."""
        self._syncing = True
        try:
            self.per_px_cb.setChecked(per_pixel)
            self.di_spin.setValue(_convert_depth(value, units, self.depth_units))
        finally:
            self._syncing = False
        self._refresh_per_pixel_label()

    def pixel_depth_size(self) -> Optional[float]:
        """Depth represented by one image pixel row, from the Y-axis calibration."""
        if not self.y_cal.ready or self.y_cal.p2 == self.y_cal.p1:
            return None
        return abs(self.y_cal.v2 - self.y_cal.v1) / abs(self.y_cal.p2 - self.y_cal.p1)

    def _on_per_pixel_toggled(self, checked: bool):
        self.di_spin.setEnabled(not checked)
        self._refresh_per_pixel_label()

    def _refresh_per_pixel_label(self):
        ps = self.pixel_depth_size()
        if ps is None:
            self.per_px_lbl.setText("Calibrate Y-axis to see depth per pixel")
        else:
            self.per_px_lbl.setText(f"1 pixel row = {ps:.5f} {self.depth_units}")

    def _on_depth_units_changed(self, new_units: str):
        old_units = self.depth_units
        self.depth_units = new_units
        self.y_grp.setTitle(f"Y-Axis Calibration  (Depth, {new_units})")
        self.di_lbl.setText(f"Depth interval ({new_units}):")

        # Convert depth interval value if units changed
        if old_units != new_units:
            current_value = self.di_spin.value()
            self.di_spin.setMinimum(self._min_interval())
            self.di_spin.setValue(_convert_depth(current_value, old_units, new_units))

    def to_state(self) -> dict:
        image_b64 = None
        if self._pil_image is not None:
            buf = io.BytesIO()
            self._pil_image.save(buf, format="PNG")
            image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return {
            "image": image_b64,
            "x_cal": [self.x_cal.p1, self.x_cal.v1, self.x_cal.p2, self.x_cal.v2],
            "y_cal": [self.y_cal.p1, self.y_cal.v1, self.y_cal.p2, self.y_cal.v2],
            "curve_color": list(self.curve_color) if self.curve_color else None,
            "markers": [list(m) for m in self._markers],
            "tolerance": self.tol_slider.value(),
            "depth_interval": self.di_spin.value(),
            "per_pixel": self.per_px_cb.isChecked(),
        }

    def apply_state(self, state: dict):
        self.clear()
        image_b64 = state.get("image")
        if image_b64:
            pil = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")
            self._set_image(pil, _pil_to_qpixmap(pil), f"{self.name} (saved)")
        else:
            self._pil_image = None
            self._img_arr = None
            self.view.clear_image()

        self.x_cal = AxisCal(*(state.get("x_cal") or [None] * 4))
        self.y_cal = AxisCal(*(state.get("y_cal") or [None] * 4))
        color = state.get("curve_color")
        self.curve_color = tuple(color) if color else None
        self._markers = [tuple(m) for m in state.get("markers", [])]
        for px, py, col, label in self._markers:
            self.view.add_marker(px, py, col, label)
        self.tol_slider.setValue(state.get("tolerance", 30))
        self._syncing = True  # restoring a saved setup should not broadcast to other tabs
        try:
            self.di_spin.setValue(state.get("depth_interval", 0.1))
            self.per_px_cb.setChecked(bool(state.get("per_pixel", False)))
        finally:
            self._syncing = False
        self._refresh_indicators()
        self._refresh_per_pixel_label()
        if self.curve_color:
            hex_col = "#{:02x}{:02x}{:02x}".format(*self.curve_color)
            self.swatch.setStyleSheet(f"background: {hex_col}; border: 1px solid #555;")
            self.color_lbl.setText(f"RGB {self.curve_color}  →  {hex_col}")

    def _refresh_indicators(self):
        for ind, ok in ((self.x1_ind, self.x_cal.p1 is not None),
                        (self.x2_ind, self.x_cal.p2 is not None),
                        (self.y1_ind, self.y_cal.p1 is not None),
                        (self.y2_ind, self.y_cal.p2 is not None)):
            ind.setText("●" if ok else "○")
            ind.setStyleSheet(f"color: {'#27ae60' if ok else '#e74c3c'}; font-size: 14px;")
        if hasattr(self, "per_px_lbl"):
            self._refresh_per_pixel_label()

    def _draw_extracted_dots(self):
        for depth, value in self.extracted:
            ex = self.x_cal.to_pixel(value)
            ey = self.y_cal.to_pixel(depth)
            if ex is not None and ey is not None:
                self.view.add_dot(ex, ey)

    def set_units_from_data(self, units: str, depth_units: str):
        self.units = units
        self.units_combo.blockSignals(True)
        self.units_combo.setCurrentText(units)
        self.units_combo.blockSignals(False)
        self.x_grp.setTitle(f"X-Axis Calibration  ({units})")

        self.depth_units = depth_units
        self.depth_units_combo.blockSignals(True)
        self.depth_units_combo.setCurrentText(depth_units)
        self.depth_units_combo.blockSignals(False)
        self.y_grp.setTitle(f"Y-Axis Calibration  (Depth, {depth_units})")
        self.di_lbl.setText(f"Depth interval ({depth_units}):")

    def _reset_x_cal(self):
        """Reset X-axis calibration"""
        self.x_cal = AxisCal()
        self.x1_ind.setText("○"); self.x1_ind.setStyleSheet("color: #e74c3c; font-size: 14px;")
        self.x2_ind.setText("○"); self.x2_ind.setStyleSheet("color: #e74c3c; font-size: 14px;")
        self._remove_calibration_markers("x")
        self._set_status("X-axis calibration reset")

    def _reset_y_cal(self):
        """Reset Y-axis calibration"""
        self.y_cal = AxisCal()
        self.y1_ind.setText("○"); self.y1_ind.setStyleSheet("color: #e74c3c; font-size: 14px;")
        self.y2_ind.setText("○"); self.y2_ind.setStyleSheet("color: #e74c3c; font-size: 14px;")
        self._remove_calibration_markers("y")
        self._set_status("Y-axis calibration reset")

    def _remove_calibration_markers(self, axis: str):
        """Remove calibration markers for specified axis"""
        to_remove = []
        for i, (px, py, color, label) in enumerate(self._markers):
            if (axis == "x" and ("X=" in label)) or (axis == "y" and ("D=" in label)):
                to_remove.append(i)

        for i in reversed(to_remove):
            self._markers.pop(i)

        self.view.clear_overlays()
        for px, py, color, label in self._markers:
            self.view.add_marker(px, py, color, label)

    # ── Interaction modes ────────────────────────────────────────────────────

    def _set_mode(self, mode: str):
        if self._pil_image is None:
            QMessageBox.information(self, "", "Load an image first")
            return
        self._mode = mode
        if mode == "pan":
            self.view.set_pan_mode()
        else:
            self.view.set_capture_mode(mode != "idle")
        msg = self._MODES.get(mode, "")
        self._set_status(msg)
        self.coord_label.setText(msg)

        # Update button appearance
        for btn, m in [(self.x1_btn, "cal_x1"), (self.x2_btn, "cal_x2"),
                       (self.y1_btn, "cal_y1"), (self.y2_btn, "cal_y2"),
                       (self.pan_btn, "pan")]:
            if m == mode:
                btn.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold;")
            else:
                btn.setStyleSheet("")

    def _on_view_click(self, scene_pos: QPointF):
        if self._img_arr is None:
            return
        px = int(np.clip(round(scene_pos.x()), 0, self._img_arr.shape[1] - 1))
        py = int(np.clip(round(scene_pos.y()), 0, self._img_arr.shape[0] - 1))
        mode = self._mode
        self._mode = "idle"
        self.view.set_capture_mode(False)

        if mode == "cal_x1":
            val = self._read_float(self.x_min_edit, "X-Min value")
            if val is None: return
            self.x_cal.p1, self.x_cal.v1 = float(px), val
            self._markers.append((px, py, "#00bfff", f"X={val}"))
            self.view.add_marker(px, py, "#00bfff", f"X={val}")
            self.x1_ind.setText("●"); self.x1_ind.setStyleSheet("color: #27ae60; font-size: 14px;")
            self._set_status(f"X-Point 1: pixel {px} = {val} {self.units}")

        elif mode == "cal_x2":
            val = self._read_float(self.x_max_edit, "Point 2 value")
            if val is None: return
            self.x_cal.p2, self.x_cal.v2 = float(px), val
            self._markers.append((px, py, "#00bfff", f"X={val}"))
            self.view.add_marker(px, py, "#00bfff", f"X={val}")
            self.x2_ind.setText("●"); self.x2_ind.setStyleSheet("color: #27ae60; font-size: 14px;")
            self._set_status(f"X-Point 2: pixel {px} = {val} {self.units}")

        elif mode == "cal_y1":
            val = self._read_float(self.y_min_edit, "Point 1 depth")
            if val is None: return
            self.y_cal.p1, self.y_cal.v1 = float(py), val
            self._markers.append((px, py, "#7fff00", f"D={val}{self.depth_units}"))
            self.view.add_marker(px, py, "#7fff00", f"D={val}{self.depth_units}")
            self.y1_ind.setText("●"); self.y1_ind.setStyleSheet("color: #27ae60; font-size: 14px;")
            self._set_status(f"Y-Point 1: pixel row {py} = {val} {self.depth_units}")

        elif mode == "cal_y2":
            val = self._read_float(self.y_max_edit, "Point 2 depth")
            if val is None: return
            self.y_cal.p2, self.y_cal.v2 = float(py), val
            self._markers.append((px, py, "#7fff00", f"D={val}{self.depth_units}"))
            self.view.add_marker(px, py, "#7fff00", f"D={val}{self.depth_units}")
            self.y2_ind.setText("●"); self.y2_ind.setStyleSheet("color: #27ae60; font-size: 14px;")
            self._set_status(f"Y-Point 2: pixel row {py} = {val} {self.depth_units}")

        elif mode == "pick_color":
            rgb = tuple(int(v) for v in self._img_arr[py, px, :3])
            self.curve_color = rgb
            hex_col = "#{:02x}{:02x}{:02x}".format(*rgb)
            self.swatch.setStyleSheet(f"background: {hex_col}; border: 1px solid #555;")
            self.color_lbl.setText(f"RGB {rgb}  →  {hex_col}")
            self._set_status(f"Curve colour sampled: {hex_col}")

        # Update coordinate readout when hovering
        self.coord_label.setText("")

    def _read_float(self, edit: QLineEdit, name: str) -> Optional[float]:
        try:
            return float(edit.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid input",
                                f"Enter a numeric value for '{name}'")
            return None

    # ── Colour mask preview ──────────────────────────────────────────────────

    def _show_mask(self):
        if self._img_arr is None:
            QMessageBox.information(self, "", "Load an image first"); return
        if self.curve_color is None:
            QMessageBox.information(self, "", "Pick a curve colour first"); return
        if not MPL_AVAILABLE:
            QMessageBox.warning(self, "", "matplotlib not available"); return

        arr = self._img_arr.astype(np.float32)
        cr, cg, cb = self.curve_color
        tol = self.tol_slider.value()
        dist = np.sqrt((arr[:, :, 0]-cr)**2 + (arr[:, :, 1]-cg)**2 + (arr[:, :, 2]-cb)**2)
        mask = (dist <= tol).astype(np.uint8) * 255

        fig, axes = plt.subplots(1, 2, figsize=(12, 6))
        axes[0].imshow(self._pil_image); axes[0].set_title("Original"); axes[0].axis("off")
        axes[1].imshow(mask, cmap="hot"); axes[1].set_title(
            f"Colour mask  (tol={tol})  —  white = matched"); axes[1].axis("off")
        plt.suptitle(f"{self.name} curve colour mask", fontsize=13)
        plt.tight_layout()
        _show_mpl_in_dialog(fig, self, f"{self.name} Colour Mask")

    # ── Data extraction ──────────────────────────────────────────────────────

    def extract_data(self):
        if self._img_arr is None:
            QMessageBox.warning(self, "", "Load an image first"); return
        if not self.x_cal.ready:
            QMessageBox.warning(self, "", "Complete X-axis calibration (X-Min and X-Max)"); return
        if not self.y_cal.ready:
            QMessageBox.warning(self, "", "Complete Y-axis calibration (Y-Min and Y-Max)"); return
        if self.curve_color is None:
            QMessageBox.warning(self, "", "Pick the curve colour first"); return

        if self.per_px_cb.isChecked():
            di = self.pixel_depth_size()
            if di is None or di <= 0:
                QMessageBox.warning(self, "Invalid", "Calibrate the Y-axis to use every pixel row"); return
            di = max(di, self._min_interval())  # never finer than the 0.1 ft floor
        else:
            try:
                di = self.di_spin.value()
                if di <= 0: raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Invalid", "Depth interval must be a positive number"); return

        arr = self._img_arr.astype(np.float32)
        cr, cg, cb = self.curve_color
        tol = float(self.tol_slider.value())

        # Colour-distance mask
        dist = np.sqrt((arr[:, :, 0]-cr)**2 + (arr[:, :, 1]-cg)**2 + (arr[:, :, 2]-cb)**2)
        mask = dist <= tol   # (H, W) boolean

        d_min = min(self.y_cal.v1, self.y_cal.v2)
        d_max = max(self.y_cal.v1, self.y_cal.v2)
        depths = np.arange(d_min, d_max + di * 0.5, di)

        results: List[Tuple[float, float]] = []
        for depth in depths:
            py = self.y_cal.to_pixel(depth)
            if py is None: continue
            r0 = max(0, int(round(py)) - 2)
            r1 = min(mask.shape[0], int(round(py)) + 3)
            if r0 >= r1: continue

            col_hits = mask[r0:r1, :].any(axis=0)
            x_indices = np.where(col_hits)[0]
            if len(x_indices) == 0: continue

            weights = mask[r0:r1, x_indices].sum(axis=0).astype(float)
            x_pos = float(np.average(x_indices, weights=weights))
            value = self.x_cal.to_value(x_pos)
            if value is not None:
                results.append((round(float(depth), 6), round(float(value), 6)))

        self.extracted = results
        # Overlay extracted dots
        self.view.clear_overlays()
        for (_, _) in []:  # clear marker list first via re-draw
            pass
        for px, py, col, lbl in self._markers:
            self.view.add_marker(px, py, col, lbl)
        for depth, value in results:
            ex = self.x_cal.to_pixel(value)
            ey = self.y_cal.to_pixel(depth)
            if ex is not None and ey is not None:
                self.view.add_dot(ex, ey)

        n = len(results)
        self.extract_lbl.setText(
            f"✓ {n} points extracted\n"
            f"   Depth: {d_min:.2f} – {d_max:.2f} {self.depth_units}\n"
            f"   Interval: {di} {self.depth_units}"
        )
        self._set_status(f"Extraction complete: {n} data points for {self.name}")

    def preview(self):
        if not self.extracted:
            QMessageBox.information(self, "", "No data extracted yet"); return
        if not MPL_AVAILABLE:
            QMessageBox.warning(self, "", "matplotlib is not available"); return

        depths = [r[0] for r in self.extracted]
        values = [r[1] for r in self.extracted]

        fig, ax = plt.subplots(figsize=(4, 9))
        ax.plot(values, depths, color=self.mpl_color, linewidth=1.4,
                marker='.', markersize=3)
        ax.invert_yaxis()
        ax.set_xlabel(f"{self.name} ({self.units})")
        ax.set_ylabel(f"Depth ({self.depth_units})")
        ax.set_title(f"{self.name}  —  {len(depths)} extracted points")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        _show_mpl_in_dialog(fig, self, f"{self.name} Preview")

    def clear(self):
        self.extracted.clear()
        self._markers.clear()
        self.x_cal = AxisCal(); self.y_cal = AxisCal()
        self.curve_color = None
        for ind in (self.x1_ind, self.x2_ind, self.y1_ind, self.y2_ind):
            ind.setText("○"); ind.setStyleSheet("color: #e74c3c; font-size: 14px;")
        self.swatch.setStyleSheet("background: #888888; border: 1px solid #555;")
        self.color_lbl.setText("No colour selected yet")
        self.extract_lbl.setText("")
        self.view.clear_overlays()
        self._set_status("Cleared")


# ─────────────────────────────────────────────────────────────────────────────
#  Main window
# ─────────────────────────────────────────────────────────────────────────────

class CPTDigitizer(QWidget):
    def __init__(self):
        super().__init__()
        self.pm = ProjectManager() if PROJECT_UI_AVAILABLE else None
        self.current_project = None
        self._build()

    def _build(self):
        # ── Main layout (vertical: toolbar, content, statusbar) ──
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Toolbar ──
        from PyQt6.QtWidgets import QToolBar
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        main_layout.addWidget(tb)

        def tact(label: str, slot, shortcut: str = ""):
            act = QAction(label, self)
            act.triggered.connect(slot)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            tb.addAction(act)
            return act

        # Project selector (if project manager available)
        if self.pm:
            tb.addWidget(QLabel("Project: "))
            self.project_combo = QComboBox()
            self.project_combo.currentTextChanged.connect(self._on_project_changed)
            tb.addWidget(self.project_combo)
            self._refresh_project_list()
            tb.addSeparator()

        # Project management
        tact("New Project", self.new_project, "")
        tact("Delete Project", self.delete_project, "")
        tb.addSeparator()

        # CPT Name input
        tb.addWidget(QLabel("CPT Name: "))
        self.cpt_name_input = QLineEdit()
        self.cpt_name_input.setPlaceholderText("e.g., BH-01, CPT-A, etc.")
        self.cpt_name_input.setMaximumWidth(150)
        tb.addWidget(self.cpt_name_input)
        tb.addSeparator()

        # Saved CPT dropdown
        tb.addWidget(QLabel("Load CPT: "))
        self.cpt_combo = QComboBox()
        self.cpt_combo.setMaximumWidth(180)
        self.cpt_combo.addItem("(No project selected)")
        self.cpt_combo.currentTextChanged.connect(self._on_cpt_combo_changed)
        tb.addWidget(self.cpt_combo)

        # Delete CPT button
        tact("Delete CPT", self.delete_cpt, "")
        tb.addSeparator()
        tb.addSeparator()
        tact("Save CPT",       self.save_to_project, "Ctrl+S")
        tb.addSeparator()
        tact("Export CSV…",   self.export_csv,   "Ctrl+Shift+S")
        tact("Export Excel…", self.export_excel, "Ctrl+E")
        tact("Export Project…", self.export_project_excel, "Ctrl+Shift+E")
        tb.addSeparator()
        tact("Preview All",   self.preview_all,  "Ctrl+P")
        tb.addSeparator()
        tact("Help",          self.show_help,    "F1")

        # ── Central: notebook ──
        nb = QTabWidget()
        nb.setDocumentMode(True)
        main_layout.addWidget(nb, 1)  # Add with stretch factor

        # Summary tab (shows all channels combined)
        self.summary_tab = self._create_summary_tab()
        nb.addTab(self.summary_tab, "  📊 Summary  (all channels)")

        self.qc = ChannelTab("qc",  "tsf", "#e74c3c")
        self.fs = ChannelTab("fs",  "tsf", "#27ae60")
        self.u2 = ChannelTab("u2",  "psi", "#2980b9")
        self.tabs = [self.qc, self.fs, self.u2]
        # Link depth interval across qc / fs / u2: editing one updates the others
        for src in self.tabs:
            src.interval_changed.connect(lambda src=src: self._sync_intervals(src))

        nb.addTab(self.qc, "  qc  (tip resistance)")
        nb.addTab(self.fs, "  fs  (sleeve friction)")
        nb.addTab(self.u2, "  u2  (pore pressure)")

        # ── Status bar ──
        self.status_bar = QStatusBar()
        main_layout.addWidget(self.status_bar)

    # ── Project management ──────────────────────────────────────────────────────

    def new_project(self):
        """Create a new project."""
        if not self.pm:
            QMessageBox.warning(self, "Warning", "Project management not available")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Create New Project")
        dlg.setMinimumWidth(280)
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel("Project Name:"))
        name_input = QLineEdit()
        name_input.setPlaceholderText("e.g., Site A, Project 2024-001")
        name_input.setFocus()
        layout.addWidget(name_input)

        btn_layout = QHBoxLayout()
        create_btn = QPushButton("Create")
        cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(create_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        def on_create():
            name = name_input.text().strip()
            if not name:
                QMessageBox.warning(dlg, "Error", "Project name is required")
                return
            try:
                self.pm.create_project(name)
                self._refresh_project_list()
                self.project_combo.setCurrentText(name)
                QMessageBox.information(dlg, "Success", f"Project '{name}' created")
                dlg.accept()
            except Exception as e:
                QMessageBox.critical(dlg, "Error", f"Failed to create project:\n{e}")

        create_btn.clicked.connect(on_create)
        cancel_btn.clicked.connect(dlg.reject)
        name_input.returnPressed.connect(on_create)
        dlg.exec()

    def _sync_intervals(self, src: "ChannelTab"):
        """Copy the depth interval from the edited tab to the other channels."""
        value = src.di_spin.value()
        units = src.depth_units
        per_pixel = src.per_px_cb.isChecked()
        for t in self.tabs:
            if t is not src:
                t.set_interval(value, units, per_pixel)

    def _load_cpt_into_channels(self, cpt_data):
        """Load CPT data into the three channel tabs."""
        channels = [
            (self.qc, cpt_data.qc, cpt_data.units_qc),
            (self.fs, cpt_data.fs, cpt_data.units_fs),
            (self.u2, cpt_data.u2, cpt_data.units_u2),
        ]
        for tab, values, units in channels:
            tab.set_units_from_data(units, cpt_data.units_depth)
            tab.apply_state(cpt_data.channel_state.get(tab.name, {}))
            tab.extracted = list(zip(cpt_data.depth, values)) if cpt_data.depth and values else []
            tab._draw_extracted_dots()
            tab._set_status(f"Loaded {len(tab.extracted)} {tab.name} points")

        # Update summary table
        self._update_summary_table()
        self.status_bar.showMessage("CPT data loaded successfully", 5000)


    def _refresh_project_list(self):
        """Refresh the project dropdown"""
        if not self.pm:
            return
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("(No project selected)")
        self.project_combo.addItems(self.pm.list_projects())
        self.project_combo.blockSignals(False)

    def _on_project_changed(self, project_name: str):
        """Handle project selection"""
        if project_name == "(No project selected)":
            self.current_project = None
            self.cpt_combo.clear()
        else:
            self.current_project = project_name
            self._refresh_cpt_list()

    def _refresh_cpt_list(self):
        """Refresh the CPT dropdown for the current project"""
        if not self.pm or not self.current_project:
            self.cpt_combo.clear()
            return
        try:
            cpt_list = self.pm.list_cpt_data(self.current_project)
            self.cpt_combo.blockSignals(True)
            self.cpt_combo.clear()
            self.cpt_combo.addItem("(Select a CPT to load)")
            if cpt_list:
                self.cpt_combo.addItems(cpt_list)
            self.cpt_combo.blockSignals(False)
        except Exception as e:
            print(f"Error refreshing CPT list: {e}")

    def _on_cpt_combo_changed(self, cpt_name: str):
        """Load selected CPT from dropdown"""
        if not cpt_name or cpt_name in ("(Select a CPT to load)", "(No project selected)", ""):
            return
        if not self.pm or not self.current_project:
            return

        try:
            cpt_data = self.pm.load_cpt_data(self.current_project, cpt_name)
            if cpt_data:
                self._load_cpt_into_channels(cpt_data)
                self.cpt_name_input.setText(cpt_name)
                self.status_bar.showMessage(f"Loaded CPT: {cpt_name}", 5000)
            else:
                QMessageBox.warning(self, "Error", f"Could not load CPT: {cpt_name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load CPT:\n{e}")

    def delete_project(self):
        """Delete the current project"""
        if not self.pm:
            QMessageBox.warning(self, "Warning", "Project management not available")
            return

        if not self.current_project:
            QMessageBox.warning(self, "Warning", "Please select a project first")
            return

        if QMessageBox.question(self, "Confirm", f"Delete project '{self.current_project}'?") == QMessageBox.StandardButton.Yes:
            try:
                self.pm.delete_project(self.current_project)
                self._refresh_project_list()
                self.project_combo.setCurrentText("(No project selected)")
                QMessageBox.information(self, "Success", f"Project '{self.current_project}' deleted")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete project:\n{e}")

    def delete_cpt(self):
        """Delete the currently selected CPT from the project"""
        if not self.pm:
            QMessageBox.warning(self, "Warning", "Project management not available")
            return

        if not self.current_project:
            QMessageBox.warning(self, "Warning", "Please select a project first")
            return

        cpt_name = self.cpt_combo.currentText()
        if cpt_name in ("(Select a CPT to load)", "(No project selected)", ""):
            QMessageBox.warning(self, "Warning", "Please select a CPT to delete")
            return

        if QMessageBox.question(self, "Confirm", f"Delete CPT '{cpt_name}'?") == QMessageBox.StandardButton.Yes:
            try:
                self.pm.delete_cpt_data(self.current_project, cpt_name)
                self._refresh_cpt_list()
                QMessageBox.information(self, "Success", f"CPT '{cpt_name}' deleted")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete CPT:\n{e}")

    def save_to_project(self):
        """Save extracted CPT data to current project"""
        if not self.pm:
            QMessageBox.warning(self, "Warning", "Project management not available")
            return

        if not self.current_project:
            QMessageBox.warning(self, "Warning", "Please select a project first")
            return

        df = self._combined_df()
        if df is None:
            QMessageBox.warning(self, "Warning", "Extract data from at least one channel first")
            return

        cpt_name = self.cpt_name_input.text().strip()
        if not cpt_name:
            QMessageBox.warning(self, "Warning", "Please enter a CPT name (e.g., BH-01)")
            return

        try:
            cpt_data = CPTData(
                depth=df["Depth_m"].tolist(),
                qc=df.get("qc", []).tolist() if "qc" in df else [],
                fs=df.get("fs", []).tolist() if "fs" in df else [],
                u2=df.get("u2", []).tolist() if "u2" in df else [],
                units_qc=self.qc.units,
                units_fs=self.fs.units,
                units_u2=self.u2.units,
                units_depth=self.qc.depth_units,
                boring_name=cpt_name,
                channel_state={t.name: t.to_state() for t in self.tabs},
            )
            self.pm.save_cpt_data(self.current_project, cpt_data)
            self._refresh_cpt_list()

            # Clear all data and CPT name for next CPT
            self.qc.clear()
            self.fs.clear()
            self.u2.clear()
            self.cpt_name_input.clear()
            self._update_summary_table()

            QMessageBox.information(self, "Success", f"CPT '{cpt_name}' saved. Ready for next CPT.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save:\n{e}")

    def _create_summary_tab(self) -> QWidget:
        """Create summary tab showing all three channels combined"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        # Title and info
        title = QLabel("CPT Data Summary")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        # ── Main content: Horizontal splitter (table left, graph right) ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: Data table ──
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(4)
        self.summary_table.setHorizontalHeaderLabels(["Depth (m)", "qc (MPa)", "fs (kPa)", "u2 (kPa)"])
        left_layout.addWidget(self.summary_table)

        # Left buttons
        left_button_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh Data")
        refresh_btn.clicked.connect(self._update_summary_table)
        left_button_row.addWidget(refresh_btn)
        left_button_row.addStretch()
        left_layout.addLayout(left_button_row)

        splitter.addWidget(left_widget)

        # ── Right: Graph preview area ──
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        graph_label = QLabel("Combined Graph Preview")
        graph_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(graph_label)

        # Image label for graph preview
        self.summary_graph_label = QLabel()
        self.summary_graph_label.setStyleSheet("background: #2b2b2b; border: 1px solid #444;")
        self.summary_graph_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_graph_label.setText("Click 'Preview' to generate graph")
        self.summary_graph_label.setMinimumWidth(400)
        self.summary_graph_label.setMinimumHeight(300)
        right_layout.addWidget(self.summary_graph_label, 1)

        # Right buttons
        right_button_row = QHBoxLayout()
        preview_btn = QPushButton("Preview Graph")
        preview_btn.clicked.connect(self.preview_all)
        right_button_row.addWidget(preview_btn)
        right_button_row.addStretch()
        right_layout.addLayout(right_button_row)

        splitter.addWidget(right_widget)
        splitter.setSizes([400, 600])  # Table: 400, Graph: 600
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter, 1)

        return widget

    def _update_summary_table(self):
        """Update summary table with extracted data"""
        df = self._combined_df()
        if df is None:
            self.summary_table.setRowCount(0)
            return

        # Update headers with actual units
        headers = [
            f"Depth ({self.qc.depth_units})",
            f"qc ({self.qc.units})",
            f"fs ({self.fs.units})",
            f"u2 ({self.u2.units})",
        ]
        self.summary_table.setHorizontalHeaderLabels(headers)

        self.summary_table.setRowCount(len(df))
        for i, row in df.iterrows():
            self.summary_table.setItem(i, 0, QTableWidgetItem(f"{row['Depth_m']:.4f}"))
            self.summary_table.setItem(i, 1, QTableWidgetItem(f"{row.get('qc', 0):.4f}"))
            self.summary_table.setItem(i, 2, QTableWidgetItem(f"{row.get('fs', 0):.4f}"))
            self.summary_table.setItem(i, 3, QTableWidgetItem(f"{row.get('u2', 0):.4f}"))

    # ── Data helpers ─────────────────────────────────────────────────────────

    def _combined_df(self) -> Optional[pd.DataFrame]:
        dfs = []
        for t in self.tabs:
            if t.extracted:
                df = pd.DataFrame(t.extracted, columns=["Depth_m", t.name])
                df = df.set_index("Depth_m")
                dfs.append(df)
        if not dfs:
            return None
        merged = dfs[0]
        for df in dfs[1:]:
            merged = merged.join(df, how="outer")
        return merged.sort_index().reset_index().rename(columns={"index": "Depth_m"})

    # ── Export ───────────────────────────────────────────────────────────────

    def _add_units_row(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add a units row as the first row of the DataFrame."""
        units_row = {}
        for col in df.columns:
            if col == "Depth_m":
                units_row[col] = self.tabs[0].depth_units  # Use first tab's depth units
            else:
                # Find the tab with this column and get its units
                for tab in self.tabs:
                    if tab.name == col:
                        units_row[col] = tab.units
                        break
        units_df = pd.DataFrame([units_row])
        return pd.concat([units_df, df], ignore_index=True).rename(columns={"Depth_m": "depth"})

    def export_csv(self):
        df = self._combined_df()
        if df is None:
            QMessageBox.information(self, "", "Extract data from at least one channel first")
            return
        df = self._add_units_row(df)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CPT Data as CSV", "cpt_data.csv", "CSV (*.csv)")
        if path:
            df.to_csv(path, index=False, float_format="%.6f")
            QMessageBox.information(self, "Saved", f"{len(df)-1} depth rows saved to:\n{path}")

    def export_excel(self):
        df = self._combined_df()
        if df is None:
            QMessageBox.information(self, "", "Extract data from at least one channel first")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CPT Data as Excel", "cpt_data.xlsx", "Excel (*.xlsx)")
        if path:
            df_with_units = self._add_units_row(df)
            with pd.ExcelWriter(path, engine="openpyxl") as wr:
                df_with_units.to_excel(wr, sheet_name="CPT Data", index=False)
                for t in self.tabs:
                    if t.extracted:
                        ch_df = pd.DataFrame(t.extracted, columns=["depth", t.name])
                        # Add units row for individual channel
                        units_row = {"depth": t.depth_units, t.name: t.units}
                        units_df = pd.DataFrame([units_row])
                        ch_df_with_units = pd.concat([units_df, ch_df], ignore_index=True)
                        ch_df_with_units.to_excel(wr, sheet_name=t.name, index=False)
                        _add_depth_chart(wr.sheets[t.name], len(ch_df), t.name, t.units, t.depth_units)

                # Summary sheet: one chart per channel, placed to the right of the table
                ws_sum = wr.sheets["CPT Data"]
                cols = list(df_with_units.columns)
                anchor_col = len(cols) + 2
                for t in self.tabs:
                    if t.extracted and t.name in cols:
                        _add_depth_chart(
                            ws_sum, len(df), t.name, t.units, t.depth_units,
                            value_col=cols.index(t.name) + 1,
                            anchor=f"{get_column_letter(anchor_col)}2",
                        )
                        anchor_col += 11  # ~one chart width of columns
            QMessageBox.information(self, "Saved", f"{len(df)} depth rows saved to:\n{path}")

    def export_project_excel(self):
        """Export every saved CPT in the current project to one workbook (one sheet per CPT)."""
        if not self.pm or not self.current_project:
            QMessageBox.warning(self, "Warning", "Please select a project first"); return
        cpts = []
        for name in self.pm.list_cpt_data(self.current_project):
            cpt = self.pm.load_cpt_data(self.current_project, name)
            if cpt is not None and cpt.depth:
                cpts.append(cpt)
        if not cpts:
            QMessageBox.information(self, "", "This project has no saved CPTs yet"); return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Project CPTs to Excel", f"{self.current_project}.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        used = set()
        with pd.ExcelWriter(path, engine="openpyxl") as wr:
            for cpt in cpts:
                _write_cpt_sheet(wr, _safe_sheet_name(cpt.boring_name, used), cpt)
        QMessageBox.information(
            self, "Saved", f"{len(cpts)} CPT(s) from project '{self.current_project}' saved to:\n{path}")

    # ── Preview all ──────────────────────────────────────────────────────────

    def preview_all(self):
        if not MPL_AVAILABLE:
            QMessageBox.warning(self, "", "matplotlib is not available"); return
        active = [t for t in self.tabs if t.extracted]
        if not active:
            QMessageBox.information(self, "", "No data extracted yet"); return

        n = len(active)
        # Use larger figure size for better readability when embedded
        fig, axes = plt.subplots(1, n, figsize=(5 * n, 8), sharey=True)
        if n == 1:
            axes = [axes]

        for ax, tab in zip(axes, active):
            depths = [r[0] for r in tab.extracted]
            values = [r[1] for r in tab.extracted]
            ax.plot(values, depths, color=tab.mpl_color, linewidth=1.4,
                    marker='.', markersize=2)
            ax.invert_yaxis()
            ax.set_xlabel(f"{tab.name} ({tab.units})", fontsize=10)
            ax.set_ylabel(f"Depth ({tab.depth_units})", fontsize=10)
            ax.set_title(tab.name, fontsize=12, fontweight="bold")
            ax.grid(True, alpha=0.3)
            ax.tick_params(labelsize=9)

        plt.suptitle("CPT Digitised Data", fontsize=12, fontweight="bold")
        plt.tight_layout()

        # Display graph in summary tab
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        buf.seek(0)
        pixmap = QPixmap()
        pixmap.loadFromData(buf.getvalue())
        # Scale to fit the label while maintaining aspect ratio
        target_height = self.summary_graph_label.height() - 10
        scaled_pixmap = pixmap.scaledToHeight(
            target_height,
            Qt.TransformationMode.SmoothTransformation
        )
        self.summary_graph_label.setPixmap(scaled_pixmap)

        plt.close(fig)  # Close the figure to free memory

    # ── Help ─────────────────────────────────────────────────────────────────

    def show_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("CPT Digitizer — Quick Start")
        dlg.resize(660, 600)
        lay = QVBoxLayout(dlg)
        from PyQt6.QtWidgets import QTextEdit
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setFont(QFont("Courier New", 10))
        txt.setPlainText(HELP_TEXT)
        lay.addWidget(txt)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        lay.addWidget(close_btn)
        dlg.exec()


# ─────────────────────────────────────────────────────────────────────────────
#  Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _pil_to_qpixmap(img: "Image.Image") -> QPixmap:
    """Convert a PIL RGB image to QPixmap without saving to disk."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    data = buf.read()
    qimg = QImage.fromData(data)
    return QPixmap.fromImage(qimg)


def _add_depth_chart(ws, n_points: int, name: str, units: str, depth_units: str,
                     value_col: int = 2, anchor: str = "D2"):
    """Add a value-vs-depth scatter chart (depth increasing downward) to a sheet.

    Depth is read from column A and values from `value_col`, starting at row 3
    (rows 1-2 hold the header and units). `anchor` is the top-left cell of the chart.
    """
    chart = ScatterChart()
    chart.scatterStyle = "lineMarker"
    chart.varyColors = False
    chart.title = f"{name} vs Depth"
    chart.x_axis.title = f"{name} ({units})"
    chart.y_axis.title = f"Depth ({depth_units})"
    chart.y_axis.scaling.orientation = "maxMin"
    chart.x_axis.crosses = "max"
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.legend = None
    chart.width = 16
    chart.height = 18

    depth_ref = Reference(ws, min_col=1, min_row=3, max_row=n_points + 2)
    value_ref = Reference(ws, min_col=value_col, min_row=3, max_row=n_points + 2)
    series = Series(depth_ref, value_ref, title=name)
    series.marker.symbol = "circle"
    series.marker.size = 5
    series.marker.graphicalProperties.solidFill = "1F4E79"
    series.marker.graphicalProperties.line.solidFill = "1F4E79"
    series.graphicalProperties.line.solidFill = "1F4E79"
    series.graphicalProperties.line.width = 19050
    series.smooth = False
    chart.series.append(series)
    ws.add_chart(chart, anchor)


def _safe_sheet_name(name: str, used: set) -> str:
    """Excel-legal, unique sheet name (max 31 chars, no []:*?/\\)."""
    base = re.sub(r"[\[\]:*?/\\]", "_", name or "").strip() or "CPT"
    base = base[:31]
    cand, i = base, 2
    while cand.lower() in used:
        suffix = f" ({i})"
        cand = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(cand.lower())
    return cand


def _write_cpt_sheet(wr, sheet: str, cpt):
    """Write one saved CPT to its own sheet (depth + channels, units row, charts)."""
    n = len(cpt.depth)
    data = {"depth": cpt.depth}
    units = {"depth": cpt.units_depth}
    for ch, vals, u in (("qc", cpt.qc, cpt.units_qc),
                        ("fs", cpt.fs, cpt.units_fs),
                        ("u2", cpt.u2, cpt.units_u2)):
        if vals and len(vals) == n and pd.Series(vals).notna().any():
            data[ch] = vals
            units[ch] = u

    df = pd.DataFrame(data)
    units_df = pd.DataFrame([units])
    pd.concat([units_df, df], ignore_index=True).to_excel(wr, sheet_name=sheet, index=False)

    ws = wr.sheets[sheet]
    cols = list(df.columns)
    anchor_col = len(cols) + 2
    for ch in cols[1:]:
        _add_depth_chart(ws, n, ch, units[ch], cpt.units_depth,
                         value_col=cols.index(ch) + 1,
                         anchor=f"{get_column_letter(anchor_col)}2")
        anchor_col += 11


def _show_mpl_in_dialog(fig, parent: QWidget, title: str):
    """Render a matplotlib figure to PNG bytes and display in a Qt dialog."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    data = buf.read()
    qimg = QImage.fromData(data)
    pix = QPixmap.fromImage(qimg)

    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(pix.width(), min(pix.height(), 900))
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(4, 4, 4, 4)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    lbl = QLabel()
    lbl.setPixmap(pix)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    scroll.setWidget(lbl)
    lay.addWidget(scroll)

    close_btn = QPushButton("Close")
    close_btn.clicked.connect(dlg.accept)
    close_btn.setFixedWidth(100)
    lay.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)
    dlg.exec()


# ─────────────────────────────────────────────────────────────────────────────
#  Help text
# ─────────────────────────────────────────────────────────────────────────────

HELP_TEXT = """\
CPT GRAPH DIGITIZER — Quick Start Guide
========================================

PURPOSE
-------
Digitises cone penetration testing (CPT) graphs from images/screenshots.
Extracts tip resistance (qc), sleeve friction (fs), and pore water
pressure (u2) at a common depth interval and exports to CSV or Excel.
Save digitised data to projects for future reference.

PROJECT WORKFLOW
----------------
1.  Create a new project: "New Project" button
2.  Digitise your CPT graphs (see below)
3.  Enter a CPT name (e.g., BH-01, CPT-A) in the toolbar
4.  Click "Save to Project" to store the data
5.  Later, click "Load CPT Data…" and select from dropdown to reload

DIGITISATION WORKFLOW  (repeat for each of the three channel tabs)
-------------------------------------------------------------------

1.  LOAD IMAGE
    • "Load Image File…"    open a PNG / JPG / BMP screenshot
    • "Capture Screen Region"  minimises this window, then drag a
      rectangle around the graph.  Press ESC to cancel.

    Tip: use the mouse wheel or Zoom +/- to magnify the graph for
    accurate clicking.  Drag normally to pan.

2.  CALIBRATE X-AXIS  (horizontal axis = measurement value)
    a.  Type the value that the LEFT end of the X-axis represents into
        the "Set X-Min" entry box  (e.g. 0).
    b.  Click the "Set X-Min →" button — the cursor changes to a cross.
    c.  Click the exact point on the graph image that corresponds to
        that minimum value (usually the left axis tick / gridline).
        The indicator turns GREEN ●.
    d.  Repeat for X-Max (the right limit of the axis).

3.  CALIBRATE Y-AXIS  (vertical axis = depth in metres)
    Same process as above.
    • Click Y-Min for the SHALLOWEST depth tick mark on the graph
      (top of the plotted region, e.g. 0 m).
    • Click Y-Max for the DEEPEST depth tick mark (bottom, e.g. 20 m).
    Depth increases downward in most CPT plots.

4.  PICK CURVE COLOUR
    a.  Click "Pick Curve Colour (click on curve)".
    b.  Click directly on the plotted line inside the graph.
    c.  The colour swatch updates.
    d.  Use "Show Colour Mask Preview" to verify — the curve should
        appear white on a dark background.  If grid lines are also
        white, DECREASE Tolerance.  If the curve is incomplete,
        INCREASE Tolerance and try again.

5.  SET DEPTH INTERVAL
    Default is 0.05 m (one reading every 5 cm).
    Use 0.1 m for coarser output matching the graph resolution.

6.  EXTRACT DATA
    Click "Extract Data".  Orange dots appear on the image showing
    every extracted data point — verify that they follow the curve.
    Click "Preview This Channel" to see a depth vs. value plot.

7.  SAVE & EXPORT
    After extracting data for all three channels:
    • "Save to Project"   — save to current project with CPT name
    • "Export CSV"        — single file with columns: Depth_m, qc, fs, u2
    • "Export Excel"      — combined sheet + one sheet per channel
    • "Export Project"    — every saved CPT in the project, one sheet per CPT

TROUBLESHOOTING
---------------
• Points missing at some depths
  → Increase Tolerance, or re-click the colour pick on a cleaner
    part of the curve (avoid anti-aliased edges).

• Wrong values / large offset
  → Re-check calibration markers — zoom in before clicking to make
    sure you are on the exact axis tick mark.

• Grid lines detected along with the curve
  → Decrease Tolerance until grid lines disappear from the mask
    preview.  Alternatively pick the colour from a grid-free section.

• Screen capture coordinates are wrong (high-DPI screens)
  → Save a screenshot manually (e.g. Windows Snipping Tool) and use
    "Load Image File…" instead.

KEYBOARD SHORTCUTS
------------------
  Ctrl+N   New Project
  Ctrl+L   Load CPT Data
  Ctrl+T   Save to Project
  Ctrl+S   Export CSV
  Ctrl+E   Export Excel
  Ctrl+Shift+E   Export Project (all saved CPTs)
  Ctrl+P   Preview All
  F1       This help window
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette
    from PyQt6.QtGui import QPalette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Base,            QColor(35, 35, 35))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Text,            QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Button,          QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.BrightText,      QColor(255, 100, 100))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(35, 35, 35))
    app.setPalette(palette)

    win = QMainWindow()
    win.setWindowTitle("CPT Graph Digitizer")
    win.resize(1600, 900)

    digitizer = CPTDigitizer()
    win.setCentralWidget(digitizer)

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
