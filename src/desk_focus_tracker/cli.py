from __future__ import annotations

import argparse
import resource
import signal
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from desk_focus_tracker.camera import CameraError, DependencyError, OpenCVCamera
from desk_focus_tracker.config import (
    ConfigurationError,
    default_model_dir,
    load_config,
    write_default_config,
)
from desk_focus_tracker.detector import create_detector
from desk_focus_tracker.domain import DetectionResult
from desk_focus_tracker.models import ModelError, ModelStore
from desk_focus_tracker.preview import PreviewError, run_preview
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

    download_parser = subparsers.add_parser(
        "download-models",
        help="download the pinned MediaPipe models",
    )
    download_parser.add_argument("--directory", type=Path, default=default_model_dir())
    download_parser.add_argument("--force", action="store_true")

    benchmark_parser = subparsers.add_parser(
        "benchmark",
        help="measure model latency and peak memory without a camera",
    )
    benchmark_parser.add_argument("--config", type=Path, help="path to a JSON configuration")
    benchmark_parser.add_argument("--iterations", type=int, default=10)

    preview_parser = subparsers.add_parser(
        "preview",
        help="show live detection evidence without saving frames",
    )
    preview_parser.add_argument("--config", type=Path, help="path to a JSON configuration")
    preview_parser.add_argument(
        "--duration",
        type=float,
        help="stop after this number of seconds",
    )
    preview_parser.add_argument(
        "--score-threshold",
        type=float,
        help="override the object detection score threshold",
    )
    preview_parser.add_argument(
        "--width",
        type=int,
        default=1280,
        help="requested preview width (default: 1280)",
    )
    preview_parser.add_argument(
        "--height",
        type=int,
        default=720,
        help="requested preview height (default: 720)",
    )
    preview_parser.add_argument(
        "--display-fps",
        type=float,
        default=60.0,
        help="requested display rate (default: 60)",
    )
    preview_parser.add_argument(
        "--inference-fps",
        type=float,
        default=10.0,
        help="background inference rate (default: 10)",
    )
    return parser


def show_status(result: DetectionResult) -> None:
    metrics = " ".join(f"{name}={value:.2f}" for name, value in result.metrics)
    suffix = f" {metrics}" if metrics else ""
    print(
        f"{result.status.value}: {result.reason} ({result.confidence:.2f}){suffix}",
        flush=True,
    )


def benchmark_detector(config_path: Path | None, iterations: int) -> int:
    if iterations <= 0:
        raise ValueError("iterations must be positive")

    import numpy as np

    config = load_config(config_path)
    started = time.perf_counter()
    detector = create_detector(config)
    loaded = time.perf_counter()
    frame = np.zeros((config.frame_height, config.frame_width, 3), dtype=np.uint8)
    latencies: list[float] = []
    result: DetectionResult | None = None
    try:
        for _ in range(iterations):
            inference_started = time.perf_counter()
            result = detector.detect(frame)
            latencies.append(time.perf_counter() - inference_started)
    finally:
        detector.close()

    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_mb = peak_rss / (1024 * 1024) if sys.platform == "darwin" else peak_rss / 1024
    print(f"model_version={detector.model_version}")
    print(f"load_seconds={loaded - started:.3f}")
    print(f"mean_inference_ms={sum(latencies) * 1000 / len(latencies):.1f}")
    print(f"peak_rss_mb={peak_rss_mb:.1f}")
    if result is not None:
        show_status(result)
    return 0


def run_tracker(config_path: Path | None, duration_seconds: float | None) -> int:
    config = load_config(config_path)
    camera = OpenCVCamera(config.camera_index, config.frame_width, config.frame_height)
    detector = create_detector(config)
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
        if arguments.command == "download-models":
            store = ModelStore(arguments.directory.expanduser())
            for path in store.download_all(force=arguments.force):
                print(f"Model ready: {path}")
            return 0
        if arguments.command == "benchmark":
            return benchmark_detector(arguments.config, arguments.iterations)
        if arguments.command == "preview":
            return run_preview(
                arguments.config,
                arguments.duration,
                arguments.score_threshold,
                arguments.width,
                arguments.height,
                arguments.display_fps,
                arguments.inference_fps,
            )
        parser.error(f"unsupported command: {arguments.command}")
    except (
        CameraError,
        ConfigurationError,
        DependencyError,
        ModelError,
        PreviewError,
        StorageError,
        ValueError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return 2
