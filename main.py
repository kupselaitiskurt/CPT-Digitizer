"""
GeoCalc Pro - Geotechnical Engineering Platform
Entry point
"""
import sys
import os

# Ensure app directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from geocalc_app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GeoCalc Pro")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("GeoCalc")

    # Apply global stylesheet
    with open(os.path.join(os.path.dirname(__file__), "geocalc_app/assets/style.qss"), "r") as f:
        app.setStyleSheet(f.read())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
