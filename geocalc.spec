# -*- mode: python ; coding: utf-8 -*-
# GeoCalc Pro - PyInstaller spec for building .exe / .app
# Run: pyinstaller geocalc.spec

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect data files
datas = [
    ('geocalc_app/assets/style.qss', 'geocalc_app/assets'),
]
datas += collect_data_files('folium')
datas += collect_data_files('branca')

# Hidden imports
hiddenimports = (
    collect_submodules('PyQt6') +
    collect_submodules('PyQt6.QtWebEngine') +
    ['pdfplumber', 'pdfminer', 'pymupdf', 'fitz',
     'folium', 'branca', 'jinja2', 'matplotlib',
     'scipy', 'anthropic', 'pandas', 'numpy']
)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GeoCalcPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='geocalc_app/assets/icon.ico',  # Add your icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GeoCalcPro',
)

# macOS app bundle
app = BUNDLE(
    coll,
    name='GeoCalcPro.app',
    icon='geocalc_app/assets/icon.icns',
    bundle_identifier='com.geocalc.pro',
    info_plist={
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'NSHighResolutionCapable': True,
    },
)
