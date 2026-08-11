from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


ROOT = Path(SPECPATH).parent
VERSION = os.environ.get("RELEASE_VERSION", "0.1.0")
mediapipe_datas = collect_data_files(
    "mediapipe",
    excludes=["**/test/**", "**/benchmark/**", "**/__pycache__/**"],
)
mediapipe_binaries = collect_dynamic_libs("mediapipe")

analysis = Analysis(
    [str(ROOT / "packaging" / "engine_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=mediapipe_binaries,
    datas=mediapipe_datas,
    hiddenimports=collect_submodules("cv2_enumerate_cameras"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["mediapipe.tasks.python.test", "mediapipe.tasks.python.benchmark"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="desk-focus-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
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
    name="DeskFocusEngine",
)
