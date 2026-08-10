from __future__ import annotations

import argparse
import signal
import sys
from collections.abc import Sequence
from pathlib import Path

from desk_focus_tracker.camera import CameraError, DependencyError, OpenCVCamera
from desk_focus_tracker.config import (
    ConfigurationError,
    load_config,
    write_default_config,
)
from desk_focus_tracker.detector import create_detector
from desk_focus_tracker.domain import DetectionResult
from desk_focus_tracker.runner import TrackerRunner
from desk_focus_tracker.storage import JsonlSessionLogger, StorageError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="desk-focus")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="start webcam tracking")
    run_parser.add_argument("--config", type=Path, help="path to a JSON configuration")
    run_parser.add_argument(
        "--duration",
        type=float,
        help="stop after this number of seconds",
    )

    init_parser = subparsers.add_parser("init-config", help="write a default configuration")
    init_parser.add_argument("--path", type=Path, default=Path("configuration.json"))
    return parser


def show_status(result: DetectionResult) -> None:
    print(f"{result.status.value}: {result.reason} ({result.confidence:.2f})", flush=True)


def run_tracker(config_path: Path | None, duration_seconds: float | None) -> int:
    config = load_config(config_path)
    camera = OpenCVCamera(config.camera_index, config.frame_width, config.frame_height)
    detector = create_detector(config.detector_backend)
    logger = JsonlSessionLogger(
        config.data_dir,
        model_version=detector.model_version,
        configuration_version=config.configuration_version,
    )
    runner = TrackerRunner(config, camera, detector, logger, show_status)

    def request_stop(_signal_number: int, _frame: object) -> None:
        runner.stop()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    runner.run(duration_seconds=duration_seconds)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "init-config":
            write_default_config(arguments.path)
            print(f"Wrote configuration: {arguments.path}")
            return 0
        if arguments.command == "run":
            return run_tracker(arguments.config, arguments.duration)
        parser.error(f"unsupported command: {arguments.command}")
    except (CameraError, ConfigurationError, DependencyError, StorageError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return 2
