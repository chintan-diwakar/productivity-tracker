from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from desk_focus_tracker.config import AppConfig
from desk_focus_tracker.domain import DetectionResult, Status
from desk_focus_tracker.runner import TrackerRunner
from desk_focus_tracker.storage import JsonlSessionLogger


class FakeCamera:
    def __init__(self) -> None:
        self.open_count = 0
        self.read_count = 0
        self.close_count = 0

    def open(self) -> None:
        self.open_count += 1

    def read(self) -> object:
        self.read_count += 1
        return object()

    def close(self) -> None:
        self.close_count += 1


class FakeDetector:
    model_version = "fake-v1"

    def __init__(self) -> None:
        self.closed = False

    def detect(self, frame: object) -> DetectionResult:
        return DetectionResult(Status.FOCUSED_SCREEN, 0.8, "focused")

    def close(self) -> None:
        self.closed = True


class FixedIdleMonitor:
    def __init__(self, seconds: float | None) -> None:
        self.seconds = seconds

    def idle_seconds(self) -> float | None:
        return self.seconds


class FakeDiagnosticWriter:
    def __init__(self) -> None:
        self.capture_count = 0
        self.closed = False

    def capture(self, frame: object, result: DetectionResult, captured_at: object) -> bool:
        self.capture_count += 1
        return True

    def close(self) -> None:
        self.closed = True


class TrackerRunnerTest(unittest.TestCase):
    def build_runner(
        self,
        data_dir: Path,
        camera: FakeCamera,
        detector: FakeDetector,
        statuses: list[Status],
        idle_seconds: float | None = None,
        diagnostic_writer: FakeDiagnosticWriter | None = None,
    ) -> TrackerRunner:
        config = AppConfig(
            data_dir=data_dir,
            model_dir=data_dir / "models",
            window_samples=1,
            minimum_matching_samples=1,
            idle_timeout_seconds=5.0,
        )
        logger = JsonlSessionLogger(data_dir, detector.model_version, 1)
        return TrackerRunner(
            config,
            camera,
            detector,
            logger,
            status_callback=lambda result: statuses.append(result.status),
            idle_monitor=FixedIdleMonitor(idle_seconds),
            diagnostic_writer=diagnostic_writer,
        )

    def test_runs_a_camera_sample_and_closes_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            camera = FakeCamera()
            detector = FakeDetector()
            statuses: list[Status] = []
            runner = self.build_runner(Path(temporary_directory), camera, detector, statuses)

            runner.run(duration_seconds=0.01)

        self.assertEqual(camera.open_count, 1)
        self.assertEqual(camera.read_count, 1)
        self.assertEqual(camera.close_count, 1)
        self.assertIn(Status.FOCUSED_SCREEN, statuses)
        self.assertTrue(detector.closed)

    def test_skips_the_camera_when_the_system_is_idle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            camera = FakeCamera()
            detector = FakeDetector()
            statuses: list[Status] = []
            runner = self.build_runner(
                Path(temporary_directory),
                camera,
                detector,
                statuses,
                idle_seconds=10.0,
            )

            runner.run(duration_seconds=0.01)

        self.assertEqual(camera.open_count, 0)
        self.assertEqual(camera.read_count, 0)
        self.assertIn(Status.SYSTEM_IDLE, statuses)

    def test_starts_paused_without_opening_the_camera(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            camera = FakeCamera()
            detector = FakeDetector()
            statuses: list[Status] = []
            runner = self.build_runner(Path(temporary_directory), camera, detector, statuses)
            runner.pause()

            runner.run(duration_seconds=0.01)

        self.assertEqual(camera.open_count, 0)
        self.assertIn(Status.PAUSED, statuses)

    def test_emits_paused_when_startup_writes_outlast_the_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            camera = FakeCamera()
            detector = FakeDetector()
            statuses: list[Status] = []
            runner = self.build_runner(Path(temporary_directory), camera, detector, statuses)
            runner.pause()
            original_prune = JsonlSessionLogger.prune

            def slow_prune(logger: JsonlSessionLogger, *args: object, **kwargs: object) -> object:
                time.sleep(0.05)
                return original_prune(logger, *args, **kwargs)

            with patch.object(JsonlSessionLogger, "prune", slow_prune):
                runner.run(duration_seconds=0.01)

        self.assertEqual(camera.open_count, 0)
        self.assertIn(Status.PAUSED, statuses)

    def test_records_saved_diagnostic_frames_in_session_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory)
            camera = FakeCamera()
            detector = FakeDetector()
            statuses: list[Status] = []
            diagnostic_writer = FakeDiagnosticWriter()
            runner = self.build_runner(
                data_dir,
                camera,
                detector,
                statuses,
                diagnostic_writer=diagnostic_writer,
            )

            runner.run(duration_seconds=0.01)

            summary_path = next((data_dir / "sessions").glob("*/summary.json"))
            summary = json.loads(summary_path.read_text())

        self.assertEqual(diagnostic_writer.capture_count, 1)
        self.assertTrue(diagnostic_writer.closed)
        self.assertEqual(summary["diagnostic_frame_count"], 1)


if __name__ == "__main__":
    unittest.main()
