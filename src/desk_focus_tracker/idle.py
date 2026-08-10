from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class IdleMonitor(Protocol):
    def idle_seconds(self) -> float | None: ...


class NullIdleMonitor:
    def idle_seconds(self) -> float | None:
        return None


@dataclass(frozen=True, slots=True)
class IdleCommand:
    arguments: tuple[str, ...]
    unit_divisor: float
    pattern: str


class CommandIdleMonitor:
    """Read idle time from the first available operating-system command."""

    def __init__(self, commands: Sequence[IdleCommand]) -> None:
        self._commands = tuple(commands)
        self._selected: IdleCommand | None = None

    def idle_seconds(self) -> float | None:
        commands = (self._selected,) if self._selected is not None else self._commands
        for command in commands:
            if command is None:
                continue
            try:
                completed = subprocess.run(
                    command.arguments,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            value = parse_idle_output(completed.stdout, command.pattern, command.unit_divisor)
            if completed.returncode == 0 and value is not None:
                self._selected = command
                return value
        self._selected = None
        return None


def parse_idle_output(output: str, pattern: str, unit_divisor: float) -> float | None:
    match = re.search(pattern, output)
    if match is None:
        return None
    try:
        return max(0.0, float(match.group(1)) / unit_divisor)
    except (ValueError, ZeroDivisionError):
        return None


def create_idle_monitor() -> IdleMonitor:
    if sys.platform == "darwin":
        return CommandIdleMonitor(
            (
                IdleCommand(
                    ("ioreg", "-c", "IOHIDSystem"),
                    1_000_000_000.0,
                    r'"HIDIdleTime"\s*=\s*(\d+)',
                ),
            )
        )
    if sys.platform.startswith("linux"):
        return CommandIdleMonitor(
            (
                IdleCommand(
                    (
                        "gdbus",
                        "call",
                        "--session",
                        "--dest",
                        "org.gnome.Mutter.IdleMonitor",
                        "--object-path",
                        "/org/gnome/Mutter/IdleMonitor/Core",
                        "--method",
                        "org.gnome.Mutter.IdleMonitor.GetIdletime",
                    ),
                    1000.0,
                    r"uint64\s+(\d+)",
                ),
                IdleCommand(("xprintidle",), 1000.0, r"(\d+)"),
            )
        )
    return NullIdleMonitor()
