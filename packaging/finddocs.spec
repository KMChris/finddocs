# -*- mode: python ; coding: utf-8 -*-
"""Konfiguracja PyInstaller dla FindDocs.

Budowanie:

    .venv/Scripts/python.exe -m PyInstaller packaging/finddocs.spec --noconfirm

Zmienne sterujace (ustawiane przez packaging/build_app.py):

    FINDDOCS_BUNDLE_MODEL  sciezka katalogu z modelem ONNX do dolaczenia
    FINDDOCS_BUILD_CONSOLE ustaw na 1, zeby zbudowac wariant z konsola do diagnostyki
"""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

SPEC_DIR = Path(SPECPATH).resolve()
PROJECT_ROOT = SPEC_DIR.parent
SRC = PROJECT_ROOT / "src"
RESOURCES = SRC / "finddocs" / "resources"

APP_NAME = "FindDocs"
CONSOLE_BUILD = os.environ.get("FINDDOCS_BUILD_CONSOLE") == "1"
MODEL_DIR = os.environ.get("FINDDOCS_BUNDLE_MODEL", "")

datas = [
    (str(RESOURCES), "finddocs/resources"),
]

# Model dolaczamy plik po pliku, zeby pominac warianty wag, ktorych aplikacja
# nie uzywa. Katalog modelu zawiera zwykle i wersje FP32, i skwantyzowana INT8;
# dolaczenie obu podwaja rozmiar instalatora bez zadnego zysku.
MODEL_SKIP = {"model.onnx"} if os.environ.get("FINDDOCS_BUNDLE_QUANTIZED", "1") == "1" else set()

if MODEL_DIR:
    model_path = Path(MODEL_DIR)
    if model_path.is_dir():
        target = f"finddocs/resources/models/{model_path.parent.name}"
        for item in sorted(model_path.iterdir()):
            if item.is_file() and item.name not in MODEL_SKIP:
                datas.append((str(item), target))

binaries = []
binaries += collect_dynamic_libs("onnxruntime")
binaries += collect_dynamic_libs("faiss")
binaries += collect_dynamic_libs("numpy")

# NumPy 2.x rozbil pakiet na podmoduly ``numpy._core``. Bez jawnego zebrania
# calego pakietu PyInstaller pomija czesc z nich i import konczy sie bledem
# "No module named 'numpy._core._exceptions'".
datas += collect_data_files("numpy")

hiddenimports = [
    "finddocs",
    "finddocs.cli",
    "finddocs.gui.app",
    "finddocs.extractors.pdf",
    "finddocs.extractors.docx",
    "finddocs.extractors.pptx",
    "finddocs.extractors.xlsx",
    "finddocs.extractors.xls_legacy",
    "finddocs.extractors.csv_table",
    "finddocs.extractors.text",
    "finddocs.extractors.html_text",
    "finddocs.extractors.rtf",
    "finddocs.extractors.eml",
    "finddocs.extractors.msg",
    "finddocs.extractors.image",
    "finddocs.extractors.doc_legacy",
    "finddocs.extractors.ppt_legacy",
    "finddocs.extractors.archive",
    "py7zr",
    "rarfile",
    "finddocs.ocr.engines.tesseract",
    "finddocs.ocr.engines.rapidocr_engine",
    "finddocs.ocr.engines.easyocr_engine",
    "finddocs.connectors.local_dir",
    "finddocs.connectors.sharepoint",
    "sqlite3",
    "encodings.idna",
    "encodings.cp1250",
    "encodings.cp1252",
    "encodings.iso8859_2",
    "win32timezone",
]
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += collect_submodules("numpy")
hiddenimports += collect_submodules("faiss")

# RapidOCR jest opcjonalny. Dolaczamy go, gdy jest zainstalowany, zeby OCR
# dzialal zaraz po instalacji, bez dodatkowych krokow po stronie uzytkownika.
try:
    import rapidocr_onnxruntime  # noqa: F401
except ImportError:
    pass
else:
    hiddenimports += collect_submodules("rapidocr_onnxruntime")
    datas += collect_data_files("rapidocr_onnxruntime")

excludes = [
    "tkinter",
    "matplotlib",
    "pytest",
    "IPython",
    "notebook",
    "torch",
    "transformers",
    "scipy",
    "pandas",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtDesigner",
]

block_cipher = None

a = Analysis(
    [str(SPEC_DIR / "launcher.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
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
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE_BUILD,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(RESOURCES / "finddocs.ico"),
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
