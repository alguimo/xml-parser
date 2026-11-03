# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Convertisseur WEDA.
# Run PyInstaller against this file to produce the packaged application.

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all

spec_dir = Path(SPECPATH)
sys.path.insert(0, str(spec_dir))

from app.icon import save_ico  # noqa: E402

APP_NAME = "Convertisseur WEDA"
BUNDLE_ID = "com.alvarodev.convertisseurweda"

icon_path = save_ico(spec_dir / "build" / "icon.ico")

datas = []
binaries = []
hiddenimports = []

# Packages that ship non-code data (themes, Tk bindings, fonts, tray backends)
# and load submodules dynamically: collect everything so the frozen app finds them.
packages = ["customtkinter", "tkinterdnd2", "reportlab"]
if sys.platform == "win32":
    packages.append("pystray")
    datas.append((str(icon_path), "."))

for package in packages:
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# Imported inside a function / optional at import time, so make them explicit.
hiddenimports += [
    "darkdetect",
    "bs4",
    "soupsieve",
    "lxml.etree",
    "packaging",
    "packaging.version",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageTk",
    "PIL.IcoImagePlugin",
]
if sys.platform == "win32":
    hiddenimports += ["six"]

a = Analysis(
    ["main.py"],
    pathex=[str(spec_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
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
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch="x86_64",
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name=APP_NAME,
    )
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier=BUNDLE_ID,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
        },
    )
else:
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
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=str(icon_path),
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
