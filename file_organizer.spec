# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path.cwd()

datas = []
for filename in ["report_template.html", "README.md"]:
    path = project_root / filename
    if path.exists():
        datas.append((str(path), "."))

hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "fitz",
    "docx",
    "openpyxl",
    "pptx",
    "jinja2",
    "yaml",
    "rich",
    "click",
    "anthropic",
    "openai",
    "packaging",
]

a = Analysis(
    ["gui.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="文件整理助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="文件整理助手",
)
