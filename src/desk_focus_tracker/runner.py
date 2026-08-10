from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from desk_focus_tracker.camera import CameraError
from desk_focus_tracker.config import AppConfig
from desk_focus_tracker.detector import Detector
from desk_focus_tracker.domain import DetectionResult, Status
from desk_focus_tracker.policy import AwayPolicy
from desk_focus_tracker.smoothing import TemporalSmoother
from desk_focus_tracker.storage import JsonlSessionLogger


class Camera(Protocol):
    def open(self) -> None: ...

    def read(self) -> object: ...

    def close(self) -> None: ...


class TrackerRunner:
    """Run the low-rate capture and classification loop."""

    def __init__(
        self,
        config: AppConfig,
        camera: Camera,
        detector: Detector,
        logger: JsonlSessionLogger,
        status_callback: Callable[[DetectionResult], None] | None = None,
    ) -> None:
        self._config = config
        self._camera = camera
        self._detector = detector
        self._logger = logger
        self._status_callback = status_callback or (lambda _result: None)
        self._stop_event = threading.Event()
        self._away_policy = AwayPolicy(config.away_timeout_seconds)
        self._smoother = TemporalSmoother(
            config.window_samples,
            config.minimum_matching_samples,
        )

    def stop(self) -> None:
        self._stop_event.set()

    def run(self, duration_seconds: float | None = None) -> None:
        if duration_seconds is not None and duration_seconds <= 0.0:
            raise ValueError("duration_seconds must be positive")

        run_started = time.monotonic()
        camera_opened = False
        logger_started = False
        try:
            self._camera.open()
            camera_opened = True
            now = datetime.now().astimezone()
            current_monotonic = time.monotonic()
            self._logger.start(self._smoother.stable, now, current_monotonic)
            logger_started = True
            self._status_callback(self._smoother.stable)

            while not self._stop_event.is_set():
                if duration_seconds is not None:
                    remaining = duration_seconds - (time.monotonic() - run_started)
                    if remaining <= 0.0:
                        break

                candidate = self._sample_once()
                sampled_monotonic = time.monotonic()
                candidate = self._away_policy.apply(candidate, sampled_monotonic)
                update = self._smoother.update(candidate)
                if update.changed:
                    self._logger.transition(
                        update.stable,
                        datetime.now().astimezone(),
                        sampled_monotonic,
                    )
                    self._status_callback(update.stable)

                interval = self._sample_interval(update.stable.status)
                if duration_seconds is not None:
                    elapsed = time.monotonic() - run_started
                    interval = min(interval, max(0.0, duration_seconds - elapsed))
                self._stop_event.wait(interval)
        finally:
            closed_at = datetime.now().astimezone()
            closed_monotonic = time.monotonic()
            try:
                if logger_started:
                    self._logger.close(closed_at, closed_monotonic)
            finally:
                try:
                    self._detector.close()
                finally:
                    if camera_opened:
                        self._camera.close()

    def _sample_once(self) -> DetectionResult:
        frame: object | None = None
        try:
            frame = self._camera.read()
            return self._detector.detect(frame)
        except CameraError as error:
            return DetectionResult(Status.CAMERA_ERROR, 1.0, str(error))
        finally:
            frame = None

    def _sample_interval(self, status: Status) -> float:
        fps = self._config.away_capture_fps if status is Status.AWAY else self._config.capture_fps
        return 1.0 / fps
