from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from know_your_focus.desktop import DesktopDependencyError


def _frontend_executable() -> Path:
    configured = os.environ.get("KYF_FRONTEND")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path
        raise DesktopDependencyError(f"GTK frontend does not exist: {path}")

    project_builds = (
        Path("desktop/target/release/know-your-focus"),
        Path("desktop/target/debug/know-your-focus"),
    )
    for path in project_builds:
        if path.is_file():
            return path

    installed = shutil.which("know-your-focus")
    if installed:
        return Path(installed)
    raise DesktopDependencyError(
        "The GTK 4 frontend is not built. Run "
        "`cargo build --manifest-path desktop/Cargo.toml`, then try again."
    )


def run_desktop(config_path: Path | None = None) -> int:
    command = [str(_frontend_executable())]
    if config_path is not None:
        command.extend(("--config", str(config_path)))
    return subprocess.run(command, check=False).returncode


def main() -> int:
    try:
        return run_desktop()
    except DesktopDependencyError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
