from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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


class TrackerRunnerTest(unittest.TestCase):
    def build_runner(
        self,
        data_dir: Path,
        camera: FakeCamera,
        detector: FakeDetector,
        statuses: list[Status],
        idle_seconds: float | None = None,
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


if __name__ == "__main__":
    unittest.main()
