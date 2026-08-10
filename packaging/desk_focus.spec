from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


ROOT = Path(SPECPATH).parent
VERSION = os.environ.get("RELEASE_VERSION", "0.1.0")
GENERATED = ROOT / "packaging" / "generated"
ICON = GENERATED / "desk-focus.icns"

mediapipe_datas = collect_data_files(
    "mediapipe",
    excludes=["**/test/**", "**/benchmark/**", "**/__pycache__/**"],
)
mediapipe_binaries = collect_dynamic_libs("mediapipe")

analysis = Analysis(
    [str(ROOT / "packaging" / "desktop_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=mediapipe_binaries,
    datas=mediapipe_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "mediapipe.tasks.python.test", "mediapipe.tasks.python.benchmark"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="desk-focus-tracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=os.environ.get("APPLE_CODESIGN_IDENTITY") or None,
    entitlements_file=None,
)
bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="DeskFocusTracker",
)

if sys.platform == "darwin":
    app = BUNDLE(
        bundle,
        name="Desk Focus Tracker.app",
        icon=str(ICON),
        bundle_identifier="dev.chintandiwakar.desk-focus-tracker",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "Desk Focus Tracker",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "13.0",
            "NSCameraUsageDescription": (
                "Desk Focus Tracker uses the camera to classify desk-focus behavior locally."
            ),
            "NSHighResolutionCapable": True,
        },
    )
