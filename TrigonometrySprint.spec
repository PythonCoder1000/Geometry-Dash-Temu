# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for Trigonometry Sprint.

Run with:
    pyinstaller TrigonometrySprint.spec

Output lands in ``dist/TrigonometrySprint/`` (a one-dir bundle). Assets
ship read-only inside the bundle; user-writable state (levels, prefs,
progress, bot_runs) goes to the OS's per-user data directory at runtime
— see ``constants._user_data_dir``.
"""
import os
import sys

_ICON_ICO = os.path.join("assets", "icon.ico")
_ICON_ICNS = os.path.join("assets", "icon.icns")
_ICON_PNG = os.path.join("assets", "icon.png")


def _icon():
    if sys.platform == "win32" and os.path.exists(_ICON_ICO):
        return _ICON_ICO
    if sys.platform == "darwin" and os.path.exists(_ICON_ICNS):
        return _ICON_ICNS
    if os.path.exists(_ICON_PNG):
        return _ICON_PNG
    return None


datas = [("assets", "assets")]
if os.path.isdir("levels"):
    datas.append(("levels", "levels"))

a = Analysis(
    ["main.py"],
    # After the 2026-04-20 reorg every game module lives inside the
    # ``src`` package. The repo root is on sys.path at runtime (main.py
    # ensures that) so PyInstaller just needs to see the package —
    # no extra pathex entries required.
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["src.server_config"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "unittest", "pydoc", "test", "pytest",
        "numpy",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="TrigonometrySprint",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=_icon(),
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False,
    name="TrigonometrySprint",
)

if sys.platform == "darwin" and os.path.exists(_ICON_ICNS):
    app = BUNDLE(
        coll,
        name="TrigonometrySprint.app",
        icon=_ICON_ICNS,
        bundle_identifier="com.trigonometrysprint.app",
        info_plist={
            "NSHighResolutionCapable": "True",
            "LSMinimumSystemVersion": "11.0",
            "CFBundleShortVersionString": "0.1.0",
        },
    )
elif sys.platform == "darwin":
    print("[TrigSprint spec] Skipping .app bundle: no assets/icon.icns. "
          "The one-dir build at dist/TrigonometrySprint/ is still complete.")
