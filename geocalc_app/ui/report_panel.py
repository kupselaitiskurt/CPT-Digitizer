"""
GeoCalc Pro - Report Import Panel
Upload PDF geotechnical reports, extract boring logs and CPT data.
"""
import os
import json
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QProgressBar, QTextEdit, QFrame, QTreeWidget,
    QTreeWidgetItem, QSplitter, QScrollArea, QDoubleSpinBox,
    QMessageBox, QLineEdit, QGroupBox, QFormLayout, QHeaderView,
    QTableWidget, QTableWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QFont, QColor

from geocalc_app.core.extractor import process_report
from geocalc_app.core.database import save_boring, save_cpt, save_report

logger = logging.getLogger(__name__)


class ExtractionWorker(QThread):
    """Background thread for PDF extraction."""
    progress = pyqtSignal(str, int)  # message, percent
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, pdf_path: str, api_key: str):
        super().__init__()
        self.pdf_path = pdf_path
        self.api_key = api_key

    def run(self):
        try:
            result = process_report(
                self.pdf_path,
                api_key=self.api_key or None,
                progress_callback=lambda msg, pct: self.progress.emit(msg, pct)
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class ReportPanel(QWidget):
    report_processed = pyqtSignal(int)  # report_id

    def __init__(self):
        super().__init__()
        self.project_id: Optional[int] = None
        self.extracted_data: Optional[dict] = None
        self.pdf_path: Optional[str] = None
        self.settings = QSettings("GeoCalc", "GeoCalcPro")
        self._build_ui()

    def set_project(self, project_id: int):
        self.project_id = project_id
        self._update_project_label()

    def _update_project_label(self):
        if self.project_id:
            from geocalc_app.core.database import get_project
            p = get_project(self.project_id)
            self.project_lbl.setText(f"Importing to: <b>{p['name']}</b>" if p else "No project")
        else:
            self.project_lbl.setText("⚠️  No project selected. Go to Projects first.")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header
        header = QLabel("Import Geotechnical Report")
        header.setObjectName("panelTitle")
        layout.addWidget(header)

        self.project_lbl = QLabel("No project selected")
        self.project_lbl.setStyleSheet("color: #666; font-size: 13px;")
        layout.addWidget(self.project_lbl)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ── Upload section ─────────────────────────────────────────────────
        upload_frame = QFrame()
        upload_frame.setObjectName("panelFrame")
        upload_layout = QVBoxLayout(upload_frame)

        # File picker row
        file_row = QHBoxLayout()
        self.file_label = QLabel("No file selected")
        self.file_label.setStyleSheet("color: #666; font-style: italic;")
        btn_browse = QPushButton("📂  Browse PDF...")
        btn_browse.setObjectName("primaryButton")
        btn_browse.clicked.connect(self._browse_pdf)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(btn_browse)
        upload_layout.addLayout(file_row)

        # API Key row
        api_row = QHBoxLayout()
        api_row.addWidget(QLabel("Claude API Key (optional — enables AI extraction):"))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-ant-... (leave blank for rule-based extraction)")
        self.api_key_edit.setText(self.settings.value("claude_api_key", ""))
        api_row.addWidget(self.api_key_edit, 1)
        upload_layout.addLayout(api_row)

        # Per-boring coordinate assignment
        coord_group = QGroupBox("Boring Coordinates  (fill after extraction — edit each row directly)")
        coord_vbox = QVBoxLayout(coord_group)

        # Quick-fill row: apply a reference point to all empty cells
        qf_row = QHBoxLayout()
        qf_row.addWidget(QLabel("Ref. Lat:"))
        self.ref_lat_spin = QDoubleSpinBox()
        self.ref_lat_spin.setRange(-90, 90)
        self.ref_lat_spin.setDecimals(6)
        self.ref_lat_spin.setSuffix("°")
        qf_row.addWidget(self.ref_lat_spin)
        qf_row.addWidget(QLabel("Lon:"))
        self.ref_lon_spin = QDoubleSpinBox()
        self.ref_lon_spin.setRange(-180, 180)
        self.ref_lon_spin.setDecimals(6)
        self.ref_lon_spin.setSuffix("°")
        qf_row.addWidget(self.ref_lon_spin)
        qf_row.addWidget(QLabel("Elev (ft):"))
        self.ref_elev_spin = QDoubleSpinBox()
        self.ref_elev_spin.setRange(-999, 9999)
        self.ref_elev_spin.setDecimals(1)
        qf_row.addWidget(self.ref_elev_spin)
        btn_fill = QPushButton("Apply to Blanks →")
        btn_fill.setToolTip("Fill empty lat/lon cells with a small offset from the reference point")
        btn_fill.clicked.connect(self._apply_ref_coords)
        qf_row.addWidget(btn_fill)
        coord_vbox.addLayout(qf_row)

        # Per-boring table
        self.coord_table = QTableWidget(0, 5)
        self.coord_table.setHorizontalHeaderLabels(
            ["Boring ID", "Latitude (°)", "Longitude (°)", "Elevation (ft)", "Total Depth (ft)"]
        )
        self.coord_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.coord_table.setMaximumHeight(180)
        self.coord_table.setToolTip("Edit Latitude, Longitude and Elevation for each boring before saving")
        coord_vbox.addWidget(self.coord_table)
        upload_layout.addWidget(coord_group)

        # Extract button
        btn_row = QHBoxLayout()
        self.btn_extract = QPushButton("⚡  Extract Data from PDF")
        self.btn_extract.setObjectName("primaryButton")
        self.btn_extract.setMinimumHeight(40)
        self.btn_extract.clicked.connect(self._run_extraction)
        self.btn_extract.setEnabled(False)
        btn_row.addWidget(self.btn_extract)
        upload_layout.addLayout(btn_row)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        upload_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #555; font-size: 12px;")
        upload_layout.addWidget(self.progress_label)

        splitter.addWidget(upload_frame)

        # ── Results section ───────────────────────────────────────────────
        results_frame = QFrame()
        results_frame.setObjectName("panelFrame")
        results_layout = QVBoxLayout(results_frame)

        results_hdr = QHBoxLayout()
        results_lbl = QLabel("Extracted Data")
        results_lbl.setObjectName("sectionLabel")
        self.btn_save = QPushButton("💾  Save to Project Database")
        self.btn_save.setObjectName("primaryButton")
        self.btn_save.clicked.connect(self._save_to_db)
        self.btn_save.setEnabled(False)
        results_hdr.addWidget(results_lbl)
        results_hdr.addStretch()
        results_hdr.addWidget(self.btn_save)
        results_layout.addLayout(results_hdr)

        # Tree view of extracted borings
        self.result_tree = QTreeWidget()
        self.result_tree.setObjectName("resultTree")
        self.result_tree.setHeaderLabels(["Item", "Value"])
        self.result_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.result_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        results_layout.addWidget(self.result_tree)

        splitter.addWidget(results_frame)
        splitter.setSizes([300, 500])

        layout.addWidget(splitter)

    def _browse_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Geotechnical Report", "",
            "PDF Files (*.pdf);;All Files (*)"
        )
        if path:
            self.pdf_path = path
            self.file_label.setText(os.path.basename(path))
            self.file_label.setStyleSheet("color: #1B3A5C; font-weight: bold;")
            self.btn_extract.setEnabled(True)

    def _run_extraction(self):
        if not self.pdf_path:
            return
        if not self.project_id:
            QMessageBox.warning(self, "No Project", "Please select a project first.")
            return

        # Save API key
        api_key = self.api_key_edit.text().strip()
        if api_key:
            self.settings.setValue("claude_api_key", api_key)

        self.btn_extract.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.result_tree.clear()

        self.worker = ExtractionWorker(self.pdf_path, api_key)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_extraction_done)
        self.worker.error.connect(self._on_extraction_error)
        self.worker.start()

    def _on_progress(self, message: str, percent: int):
        self.progress_bar.setValue(percent)
        self.progress_label.setText(message)

    def _on_extraction_done(self, result: dict):
        self.extracted_data = result
        self.progress_bar.setValue(100)
        self.btn_extract.setEnabled(True)

        borings = result.get("borings", [])

        # Populate coordinate table so user can review / edit before saving
        self.coord_table.setRowCount(len(borings))
        for i, b in enumerate(borings):
            id_item = QTableWidgetItem(b.get("boring_id", ""))
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.coord_table.setItem(i, 0, id_item)

            lat_val = b.get("latitude")
            lon_val = b.get("longitude")
            elev_val = b.get("elevation")
            depth_val = b.get("total_depth")

            self.coord_table.setItem(i, 1, QTableWidgetItem(str(lat_val) if lat_val is not None else ""))
            self.coord_table.setItem(i, 2, QTableWidgetItem(str(lon_val) if lon_val is not None else ""))
            self.coord_table.setItem(i, 3, QTableWidgetItem(str(elev_val) if elev_val is not None else ""))
            depth_item = QTableWidgetItem(str(depth_val) if depth_val is not None else "")
            depth_item.setFlags(depth_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.coord_table.setItem(i, 4, depth_item)

        self._populate_tree(result)
        self.btn_save.setEnabled(True)
        boring_ct = len(borings)
        cpt_ct = len(result.get("cpt_soundings", []))
        # Pre-fill ref spinboxes from geocoded coordinates
        if result.get("_geocoded_lat"):
            self.ref_lat_spin.setValue(result["_geocoded_lat"])
            self.ref_lon_spin.setValue(result["_geocoded_lon"])

        geo_addr = result.get("_geocoded_address")
        if geo_addr:
            geo_msg = f"  |  Located: {geo_addr[:50]}"
        else:
            geo_msg = "  |  No address found — enter coordinates in table below"
        self.progress_label.setText(
            f"✅  {boring_ct} borings, {cpt_ct} CPT soundings{geo_msg}"
        )

    def _on_extraction_error(self, error_msg: str):
        self.btn_extract.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setText(f"❌ Error: {error_msg}")
        QMessageBox.critical(self, "Extraction Error", f"Failed to extract data:\n{error_msg}")

    def _apply_ref_coords(self):
        """Fill empty lat/lon/elev cells using reference point + small offsets."""
        ref_lat = self.ref_lat_spin.value()
        ref_lon = self.ref_lon_spin.value()
        ref_elev = self.ref_elev_spin.value()
        if ref_lat == 0.0 and ref_lon == 0.0:
            QMessageBox.information(self, "No Reference",
                                    "Enter a reference Latitude and Longitude first.")
            return
        offset_per_boring = 0.000138  # ~50 ft northward per boring
        for i in range(self.coord_table.rowCount()):
            lat_item = self.coord_table.item(i, 1)
            if not lat_item or not lat_item.text().strip():
                self.coord_table.setItem(i, 1,
                    QTableWidgetItem(f"{ref_lat + i * offset_per_boring:.6f}"))
                self.coord_table.setItem(i, 2,
                    QTableWidgetItem(f"{ref_lon:.6f}"))
            if ref_elev != 0.0:
                elev_item = self.coord_table.item(i, 3)
                if not elev_item or not elev_item.text().strip():
                    self.coord_table.setItem(i, 3, QTableWidgetItem(f"{ref_elev:.1f}"))

    def _populate_tree(self, data: dict):
        self.result_tree.clear()

        # Report metadata
        meta = data.get("report_metadata", {})
        meta_item = QTreeWidgetItem(["📋 Report Info", ""])
        for k, v in meta.items():
            if v:
                QTreeWidgetItem(meta_item, [k.replace("_", " ").title(), str(v)])
        self.result_tree.addTopLevelItem(meta_item)
        meta_item.setExpanded(True)

        # Borings
        borings = data.get("borings", [])
        borings_root = QTreeWidgetItem([f"🔵 Borings ({len(borings)})", ""])
        for b in borings:
            b_item = QTreeWidgetItem(borings_root, [
                b.get("boring_id", "Unknown"),
                f"Depth: {b.get('total_depth') or '?'} ft | "
                f"{'GWT: ' + str(b.get('water_table')) + ' ft' if b.get('water_table') else 'GWT: N/A'}"
            ])
            if b.get("latitude"):
                QTreeWidgetItem(b_item, ["Coordinates",
                                         f"{b['latitude']:.6f}, {b['longitude']:.6f}"])
            QTreeWidgetItem(b_item, ["Layers", str(len(b.get("layers", [])))])

            for layer in b.get("layers", [])[:5]:
                layer_item = QTreeWidgetItem(b_item, [
                    f"  {layer['depth_top']:.1f}–{layer['depth_bottom']:.1f} ft",
                    f"{layer.get('uscs_symbol','')}  {layer.get('soil_description','')[:60]}"
                ])
                if layer.get("n_value"):
                    layer_item.setText(1, layer_item.text(1) + f"  N={layer['n_value']}")

            if len(b.get("layers", [])) > 5:
                QTreeWidgetItem(b_item, ["...", f"+{len(b['layers'])-5} more layers"])

        self.result_tree.addTopLevelItem(borings_root)
        borings_root.setExpanded(True)

        # CPTs
        cpts = data.get("cpt_soundings", [])
        if cpts:
            cpt_root = QTreeWidgetItem([f"🔴 CPT Soundings ({len(cpts)})", ""])
            for c in cpts:
                c_item = QTreeWidgetItem(cpt_root, [
                    c.get("cpt_id", "Unknown"),
                    f"{len(c.get('data_points', []))} data points"
                ])
                if c.get("latitude"):
                    QTreeWidgetItem(c_item, ["Coordinates",
                                             f"{c['latitude']:.6f}, {c['longitude']:.6f}"])
            self.result_tree.addTopLevelItem(cpt_root)
            cpt_root.setExpanded(True)

        self.result_tree.resizeColumnToContents(0)

    def _save_to_db(self):
        if not self.extracted_data or not self.project_id:
            return

        try:
            # Save report record
            meta = self.extracted_data.get("report_metadata", {})
            report_id = save_report(
                project_id=self.project_id,
                filename=os.path.basename(self.pdf_path or "unknown.pdf"),
                file_path=self.pdf_path or "",
                raw_text=self.extracted_data.get("raw_text", ""),
                lab_firm=meta.get("lab_firm", "")
            )

            # Apply any coordinate edits from the table back onto the data
            borings = self.extracted_data.get("borings", [])
            for i, b in enumerate(borings):
                if i >= self.coord_table.rowCount():
                    break

                def _cell(col):
                    item = self.coord_table.item(i, col)
                    return item.text().strip() if item else ""

                for field, col in (("latitude", 1), ("longitude", 2), ("elevation", 3)):
                    txt = _cell(col)
                    if txt:
                        try:
                            b[field] = float(txt)
                        except ValueError:
                            pass

            # Save borings
            boring_ct = 0
            for b in borings:
                save_boring(self.project_id, report_id, b)
                boring_ct += 1

            # Save CPTs
            cpt_ct = 0
            for c in self.extracted_data.get("cpt_soundings", []):
                save_cpt(self.project_id, report_id, c)
                cpt_ct += 1

            QMessageBox.information(
                self, "Saved",
                f"Successfully saved:\n"
                f"• {boring_ct} boring{'s' if boring_ct != 1 else ''}\n"
                f"• {cpt_ct} CPT sounding{'s' if cpt_ct != 1 else ''}\n\n"
                f"Data is now available in the Site Map and Fence Diagram views."
            )

            self.report_processed.emit(report_id)
            self.extracted_data = None
            self.btn_save.setEnabled(False)
            self.result_tree.clear()
            self.progress_label.setText("Saved to database.")

        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save data:\n{str(e)}")
            logger.exception("Save error")
