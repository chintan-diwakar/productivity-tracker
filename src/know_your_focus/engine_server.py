from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from know_your_focus.desktop import DesktopController, DesktopSnapshot


class EngineProtocolError(ValueError):
    """Raised when the desktop frontend sends an invalid request."""


def snapshot_mapping(snapshot: DesktopSnapshot) -> dict[str, object]:
    return {
        "status": snapshot.status.value,
        "status_seconds": snapshot.status_seconds,
        "metrics": snapshot.metrics.to_mapping(),
        "session_metrics": (
            snapshot.session_metrics.to_mapping() if snapshot.session_metrics is not None else None
        ),
        "last_sample": (
            snapshot.last_sample.isoformat() if snapshot.last_sample is not None else None
        ),
        "running": snapshot.running,
        "paused": snapshot.paused,
        "error": snapshot.error,
    }


class EngineService:
    """Expose the Python tracking controller through a JSON Lines protocol."""

    def __init__(self, controller: DesktopController) -> None:
        self.controller = controller

    def execute(self, command: str, arguments: Mapping[str, Any]) -> object:
        if command == "snapshot":
            return snapshot_mapping(self.controller.snapshot())
        if command == "config":
            return self.controller.config.to_mapping()
        if command == "models_ready":
            return self.controller.models_ready()
        if command == "list_cameras":
            return [camera.to_mapping() for camera in self.controller.available_cameras()]
        if command == "start":
            self.controller.start()
            return None
        if command == "pause":
            self.controller.pause()
            return None
        if command == "pause_for":
            self.controller.pause(_positive_number(arguments, "seconds"))
            return None
        if command == "end_session":
            self.controller.end_session()
            return None
        if command == "save_camera_index":
            camera_index = _integer(arguments, "camera_index")
            self.controller.save_camera_index(camera_index)
            return self.controller.config.to_mapping()
        if command == "download_models":
            return [str(path) for path in self.controller.download_models()]
        if command == "preview":
            self.controller.preview()
            return None
        if command == "calibrate":
            result = self.controller.calibrate()
            return {
                "neutral_pitch_degrees": result.neutral_pitch_degrees,
                "samples": result.samples,
                "spread_degrees": result.spread_degrees,
            }
        if command == "session_summaries":
            return self.controller.session_summaries()
        if command == "save_diagnostic_setting":
            enabled = arguments.get("enabled")
            if not isinstance(enabled, bool):
                raise EngineProtocolError("enabled must be true or false")
            self.controller.save_diagnostic_setting(enabled)
            return self.controller.config.to_mapping()
        if command == "open_data_folder":
            self.controller.open_data_folder()
            return None
        if command == "open_session_folder":
            self.controller.open_session_folder()
            return None
        if command == "delete_history":
            return [str(path) for path in self.controller.delete_history()]
        if command == "shutdown":
            self.controller.stop()
            return None
        raise EngineProtocolError(f"unsupported command: {command}")


def _integer(arguments: Mapping[str, Any], name: str) -> int:
    value = arguments.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise EngineProtocolError(f"{name} must be an integer")
    return value


def _positive_number(arguments: Mapping[str, Any], name: str) -> float:
    value = arguments.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EngineProtocolError(f"{name} must be a number")
    number = float(value)
    if number <= 0.0:
        raise EngineProtocolError(f"{name} must be positive")
    return number


def serve(
    service: EngineService,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    for raw_line in input_stream:
        request_id: object = None
        shutdown = False
        try:
            request = json.loads(raw_line)
            if not isinstance(request, dict):
                raise EngineProtocolError("request must be a JSON object")
            request_id = request.get("id")
            command = request.get("command")
            arguments = request.get("arguments", {})
            if not isinstance(command, str) or not command:
                raise EngineProtocolError("command must be a non-empty string")
            if not isinstance(arguments, dict):
                raise EngineProtocolError("arguments must be a JSON object")
            result = service.execute(command, arguments)
            response = {"id": request_id, "ok": True, "result": result}
            shutdown = command == "shutdown"
        except Exception as error:
            response = {
                "id": request_id,
                "ok": False,
                "error": str(error) or error.__class__.__name__,
            }
        output_stream.write(json.dumps(response, separators=(",", ":")) + "\n")
        output_stream.flush()
        if shutdown:
            return 0
    service.controller.stop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="desk-focus-engine")
    parser.add_argument("--config", type=Path, help="path to a JSON configuration")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return serve(EngineService(DesktopController(arguments.config)))


if __name__ == "__main__":
    raise SystemExit(main())
