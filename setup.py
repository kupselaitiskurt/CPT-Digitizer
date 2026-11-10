"""
GeoCalc Pro - Setup & Build Configuration
"""
from setuptools import setup, find_packages

setup(
    name="geocalc-pro",
    version="1.0.0",
    description="Geotechnical Engineering Analysis Platform",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "PyQt6>=6.6.0",
        "PyQt6-WebEngine>=6.6.0",
        "pdfplumber>=0.11.0",
        "PyMuPDF>=1.24.0",
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "folium>=0.16.0",
        "requests>=2.31.0",
        "matplotlib>=3.8.0",
        "scipy>=1.11.0",
        "anthropic>=0.30.0",
    ],
    package_data={
        "geocalc_app": ["assets/*.qss", "assets/*.png", "assets/*.ico"],
    },
    entry_points={
        "console_scripts": [
            "geocalc=main:main",
        ],
    },
)
