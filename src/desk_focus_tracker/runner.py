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
from desk_focus_tracker.idle import IdleMonitor, NullIdleMonitor
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
        sample_callback: Callable[[datetime], None] | None = None,
        idle_monitor: IdleMonitor | None = None,
    ) -> None:
        self._config = config
        self._camera = camera
        self._detector = detector
        self._logger = logger
        self._status_callback = status_callback or (lambda _result: None)
        self._sample_callback = sample_callback or (lambda _sampled_at: None)
        self._idle_monitor = idle_monitor or NullIdleMonitor()
        self._condition = threading.Condition()
        self._stop_requested = False
        self._pause_requested = False
        self._pause_deadline: float | None = None
        self._paused = False
        self._camera_opened = False
        self._away_policy = AwayPolicy(config.away_timeout_seconds)
        self._smoother = TemporalSmoother(
            config.window_samples,
            config.minimum_matching_samples,
        )

    @property
    def paused(self) -> bool:
        with self._condition:
            return self._paused or self._pause_requested

    def stop(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()

    def pause(self, duration_seconds: float | None = None) -> None:
        if duration_seconds is not None and duration_seconds <= 0.0:
            raise ValueError("duration_seconds must be positive")
        with self._condition:
            self._pause_requested = True
            self._pause_deadline = (
                time.monotonic() + duration_seconds if duration_seconds is not None else None
            )
            self._condition.notify_all()

    def resume(self) -> None:
        with self._condition:
            self._pause_requested = False
            self._pause_deadline = None
            self._condition.notify_all()

    def run(self, duration_seconds: float | None = None) -> None:
        if duration_seconds is not None and duration_seconds <= 0.0:
            raise ValueError("duration_seconds must be positive")

        run_started = time.monotonic()
        logger_started = False
        try:
            now = datetime.now().astimezone()
            current_monotonic = time.monotonic()
            self._logger.start(self._smoother.stable, now, current_monotonic)
            self._logger.prune(self._config.retention_days, today=now.date())
            logger_started = True
            self._status_callback(self._smoother.stable)

            while not self._stop_is_requested():
                current_monotonic = time.monotonic()
                if duration_seconds is not None:
                    remaining = duration_seconds - (current_monotonic - run_started)
                    if remaining <= 0.0:
                        break

                now = datetime.now().astimezone()
                self._logger.checkpoint(now, current_monotonic)
                if self._pause_is_active(current_monotonic):
                    self._enter_paused_state(now, current_monotonic)
                    self._wait(
                        self._pause_wait_seconds(current_monotonic, duration_seconds, run_started)
                    )
                    continue
                self._leave_paused_state(now, current_monotonic)

                idle_seconds = self._idle_monitor.idle_seconds()
                if (
                    idle_seconds is not None
                    and self._config.idle_timeout_seconds > 0.0
                    and idle_seconds >= self._config.idle_timeout_seconds
                ):
                    self._close_camera()
                    self._set_immediate_status(
                        DetectionResult(
                            Status.SYSTEM_IDLE,
                            1.0,
                            "system_input_idle",
                            (("idle_seconds", idle_seconds),),
                        ),
                        now,
                        current_monotonic,
                    )
                else:
                    self._sample_and_update(now, current_monotonic)

                interval = self._sample_interval(self._smoother.stable.status)
                if duration_seconds is not None:
                    remaining = duration_seconds - (time.monotonic() - run_started)
                    interval = min(interval, max(0.0, remaining))
                self._wait(interval)
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
                    self._close_camera()

    def _sample_and_update(self, now: datetime, monotonic_seconds: float) -> None:
        if not self._ensure_camera_open(now, monotonic_seconds):
            return
        if self._smoother.stable.status in {Status.CAMERA_ERROR, Status.SYSTEM_IDLE}:
            self._set_immediate_status(
                DetectionResult(Status.UNCERTAIN, 0.0, "camera_ready"),
                now,
                monotonic_seconds,
            )

        candidate = self._sample_once()
        sampled_monotonic = time.monotonic()
        if candidate.status is not Status.CAMERA_ERROR:
            self._sample_callback(datetime.now().astimezone())
        else:
            self._close_camera()
        candidate = self._away_policy.apply(candidate, sampled_monotonic)
        update = self._smoother.update(candidate)
        if update.changed:
            self._logger.transition(
                update.stable,
                datetime.now().astimezone(),
                sampled_monotonic,
            )
            self._status_callback(update.stable)

    def _ensure_camera_open(self, now: datetime, monotonic_seconds: float) -> bool:
        if self._camera_opened:
            return True
        try:
            self._camera.open()
        except CameraError as error:
            self._set_immediate_status(
                DetectionResult(Status.CAMERA_ERROR, 1.0, str(error)),
                now,
                monotonic_seconds,
            )
            return False
        self._camera_opened = True
        return True

    def _sample_once(self) -> DetectionResult:
        frame: object | None = None
        try:
            frame = self._camera.read()
            return self._detector.detect(frame)
        except CameraError as error:
            return DetectionResult(Status.CAMERA_ERROR, 1.0, str(error))
        finally:
            frame = None

    def _set_immediate_status(
        self,
        result: DetectionResult,
        now: datetime,
        monotonic_seconds: float,
    ) -> None:
        previous_status = self._smoother.stable.status
        self._smoother.reset(result)
        self._away_policy.reset()
        if result.status is not previous_status:
            self._logger.transition(result, now, monotonic_seconds)
            self._status_callback(result)

    def _enter_paused_state(self, now: datetime, monotonic_seconds: float) -> None:
        if self._paused:
            return
        self._close_camera()
        self._set_immediate_status(
            DetectionResult(Status.PAUSED, 1.0, "tracking_paused"),
            now,
            monotonic_seconds,
        )
        with self._condition:
            self._paused = True

    def _leave_paused_state(self, now: datetime, monotonic_seconds: float) -> None:
        if not self._paused:
            return
        self._set_immediate_status(
            DetectionResult(Status.UNCERTAIN, 0.0, "tracking_resumed"),
            now,
            monotonic_seconds,
        )
        with self._condition:
            self._paused = False

    def _pause_is_active(self, monotonic_seconds: float) -> bool:
        with self._condition:
            if self._pause_deadline is not None and monotonic_seconds >= self._pause_deadline:
                self._pause_requested = False
                self._pause_deadline = None
            return self._pause_requested

    def _pause_wait_seconds(
        self,
        monotonic_seconds: float,
        duration_seconds: float | None,
        run_started: float,
    ) -> float:
        waits = [1.0]
        with self._condition:
            if self._pause_deadline is not None:
                waits.append(max(0.0, self._pause_deadline - monotonic_seconds))
        if duration_seconds is not None:
            waits.append(max(0.0, duration_seconds - (monotonic_seconds - run_started)))
        return min(waits)

    def _sample_interval(self, status: Status) -> float:
        fps = (
            self._config.away_capture_fps
            if status in {Status.AWAY, Status.SYSTEM_IDLE, Status.CAMERA_ERROR}
            else self._config.capture_fps
        )
        return 1.0 / fps

    def _stop_is_requested(self) -> bool:
        with self._condition:
            return self._stop_requested

    def _wait(self, seconds: float) -> None:
        with self._condition:
            self._condition.wait(timeout=seconds)

    def _close_camera(self) -> None:
        if self._camera_opened:
            self._camera.close()
        self._camera_opened = False
