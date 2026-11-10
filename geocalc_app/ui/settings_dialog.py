"""
GeoCalc Pro - Settings Dialog
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QDialogButtonBox, QFormLayout, QGroupBox,
    QTabWidget, QWidget, QCheckBox, QSpinBox, QFileDialog
)
from PyQt6.QtCore import QSettings
import os


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GeoCalc Pro — Settings")
        self.setMinimumWidth(520)
        self.settings = QSettings("GeoCalc", "GeoCalcPro")
        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>Settings</h2>"))

        tabs = QTabWidget()

        # ── AI / API tab ──────────────────────────────────────────────────
        ai_tab = QWidget()
        ai_layout = QVBoxLayout(ai_tab)

        api_group = QGroupBox("Claude AI (Anthropic)")
        api_form = QFormLayout(api_group)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-ant-api03-...")
        api_form.addRow("API Key:", self.api_key_edit)

        info = QLabel(
            "Claude AI is used for intelligent extraction of boring log data from PDFs. "
            "Without an API key, GeoCalc will use rule-based extraction which works for "
            "standard boring log formats. Get a key at console.anthropic.com"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #666; font-size: 12px;")
        api_form.addRow(info)

        ai_layout.addWidget(api_group)
        ai_layout.addStretch()
        tabs.addTab(ai_tab, "AI & API")

        # ── Units tab ─────────────────────────────────────────────────────
        units_tab = QWidget()
        units_layout = QVBoxLayout(units_tab)
        units_group = QGroupBox("Default Units")
        units_form = QFormLayout(units_group)
        self.units_imperial = QCheckBox("Imperial (feet, psi, pcf)")
        self.units_imperial.setChecked(True)
        units_form.addRow(self.units_imperial)
        units_layout.addWidget(units_group)
        units_layout.addStretch()
        tabs.addTab(units_tab, "Units")

        # ── Database tab ──────────────────────────────────────────────────
        db_tab = QWidget()
        db_layout = QVBoxLayout(db_tab)
        db_group = QGroupBox("Database Location")
        db_form = QFormLayout(db_group)

        from geocalc_app.core.database import get_db_path
        db_path_lbl = QLabel(get_db_path())
        db_path_lbl.setStyleSheet("color: #333; font-family: monospace;")
        db_form.addRow("Current DB:", db_path_lbl)

        btn_backup = QPushButton("📦  Backup Database...")
        btn_backup.clicked.connect(self._backup_db)
        db_form.addRow(btn_backup)

        db_layout.addWidget(db_group)
        db_layout.addStretch()
        tabs.addTab(db_tab, "Database")

        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_settings)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_settings(self):
        self.api_key_edit.setText(self.settings.value("claude_api_key", ""))

    def _save_settings(self):
        self.settings.setValue("claude_api_key", self.api_key_edit.text().strip())
        self.accept()

    def _backup_db(self):
        from geocalc_app.core.database import get_db_path
        dest, _ = QFileDialog.getSaveFileName(
            self, "Backup Database", "geocalc_backup.db", "SQLite DB (*.db)"
        )
        if dest:
            import shutil
            shutil.copy(get_db_path(), dest)
