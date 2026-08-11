from __future__ import annotations

import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from know_your_focus.calibration import CalibrationResult, calibrate_neutral_head
from know_your_focus.camera import CameraDevice, OpenCVCamera, enumerate_camera_devices
from know_your_focus.config import (
    AppConfig,
    default_config_path,
    load_config,
    write_config,
    write_default_config,
)
from know_your_focus.detector import create_detector
from know_your_focus.diagnostics import DiagnosticFrameWriter
from know_your_focus.domain import DetectionResult, Status
from know_your_focus.idle import create_idle_monitor
from know_your_focus.instance_lock import InstanceLock, data_directory_lock
from know_your_focus.metrics import DailyMetrics, SessionMetrics
from know_your_focus.models import ModelStore
from know_your_focus.preview import run_preview
from know_your_focus.runner import TrackerRunner
from know_your_focus.storage import JsonlSessionLogger


class DesktopDependencyError(RuntimeError):
    """Raised when the desktop UI dependency is not installed."""


class DesktopBusyError(RuntimeError):
    """Raised when two operations try to use the camera at the same time."""


STATUS_LABELS = {
    Status.FOCUSED_SCREEN: "Focused",
    Status.POSSIBLE_PHONE_USE: "Possible phone use",
    Status.LOOKING_DOWN: "Looking down · uncertain",
    Status.LOOKING_AWAY: "Looking away · person visible",
    Status.AWAY: "Away · no person visible",
    Status.SYSTEM_IDLE: "System idle",
    Status.UNCERTAIN: "Uncertain",
    Status.PAUSED: "Paused",
    Status.CAMERA_ERROR: "Camera error",
}


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class DesktopSnapshot:
    status: Status
    status_seconds: float
    metrics: DailyMetrics
    session_metrics: SessionMetrics | None
    last_sample: datetime | None
    running: bool
    paused: bool
    error: str | None


class DesktopController:
    """Own the tracking thread and expose thread-safe desktop actions."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or default_config_path()
        if not self.config_path.exists():
            write_default_config(self.config_path)
        self._config = load_config(self.config_path)
        self._lock = threading.RLock()
        self._runner: TrackerRunner | None = None
        self._logger: JsonlSessionLogger | None = None
        self._thread: threading.Thread | None = None
        self._instance_lock: InstanceLock | None = None
        self._status = Status.PAUSED
        self._status_started = time.monotonic()
        self._last_sample: datetime | None = None
        self._error: str | None = None
        self._camera_operation_lock = threading.Lock()
        self._active_camera_operation: str | None = None

    @property
    def config(self) -> AppConfig:
        with self._lock:
            return self._config

    def models_ready(self) -> bool:
        try:
            ModelStore(self.config.model_dir).require_all()
        except Exception:
            return False
        return True

    def available_cameras(self) -> tuple[CameraDevice, ...]:
        return enumerate_camera_devices()

    def download_models(self) -> tuple[Path, ...]:
        paths = tuple(ModelStore(self.config.model_dir).download_all())
        with self._lock:
            self._error = None
        return paths

    def start(self) -> None:
        with self._camera_operation("starting tracking"), self._lock:
            if self._thread is not None and self._thread.is_alive():
                assert self._runner is not None
                self._runner.resume()
                return

            config = load_config(self.config_path)
            ModelStore(config.model_dir).require_all()
            instance_lock = data_directory_lock(config.data_dir)
            instance_lock.acquire()
            try:
                camera = OpenCVCamera(
                    config.camera_index,
                    config.frame_width,
                    config.frame_height,
                )
                detector = create_detector(config)
                logger = JsonlSessionLogger(
                    config.data_dir,
                    model_version=detector.model_version,
                    configuration_version=config.configuration_version,
                    diagnostic_output_enabled=config.save_diagnostic_frames,
                )
                logger.recover_interrupted_sessions()
                diagnostic_writer = (
                    DiagnosticFrameWriter(
                        logger.session_directory,
                        config.diagnostic_frame_limit,
                    )
                    if config.save_diagnostic_frames
                    else None
                )
                runner = TrackerRunner(
                    config,
                    camera,
                    detector,
                    logger,
                    status_callback=self._set_status,
                    sample_callback=self._set_last_sample,
                    idle_monitor=create_idle_monitor(),
                    diagnostic_writer=diagnostic_writer,
                    diagnostic_error_callback=self._set_diagnostic_error,
                )
            except Exception:
                instance_lock.release()
                raise
            self._config = config
            self._logger = logger
            self._runner = runner
            self._instance_lock = instance_lock
            self._error = None
            self._last_sample = None
            self._thread = threading.Thread(
                target=self._run_tracker,
                args=(runner,),
                name="know-your-focus",
                daemon=True,
            )
            self._thread.start()

    def pause(self, duration_seconds: float | None = None) -> None:
        with self._lock:
            if self._runner is None or self._thread is None or not self._thread.is_alive():
                self._set_status(DetectionResult(Status.PAUSED, 1.0, "tracking_not_started"))
                return
            self._runner.pause(duration_seconds)

    def resume(self) -> None:
        self.start()

    def end_session(self) -> None:
        self.stop()

    def stop(self) -> None:
        with self._lock:
            runner = self._runner
            thread = self._thread
        if runner is not None:
            runner.stop()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=10.0)
        with self._lock:
            self._set_status(DetectionResult(Status.PAUSED, 1.0, "tracking_stopped"))

    def save_camera_index(self, camera_index: int) -> None:
        if camera_index < 0:
            raise ValueError("camera_index must be zero or greater")
        with self._camera_operation("saving camera settings"):
            config = load_config(self.config_path)
            if config.camera_index == camera_index:
                with self._lock:
                    self._config = config
                return
            self.stop()
            with self._lock:
                self._config = replace(config, camera_index=camera_index)
                write_config(self.config_path, self._config)

    def calibrate(self) -> CalibrationResult:
        with self._camera_operation("calibration"):
            self.stop()
            with self._lock:
                self._error = None
            config = load_config(self.config_path)
            result = calibrate_neutral_head(config)
            write_config(self.config_path, result.config)
            with self._lock:
                self._config = result.config
            return result

    def preview(self) -> None:
        with self._camera_operation("camera preview"):
            self.stop()
            with self._lock:
                self._error = None
            run_preview(
                self.config_path,
                duration_seconds=None,
                score_threshold=None,
                preview_width=1280,
                preview_height=720,
                display_fps=60.0,
                inference_fps=10.0,
                zoom=0.0,
            )

    def open_data_folder(self) -> None:
        self._open_folder(self.config.data_dir)

    def open_session_folder(self) -> None:
        with self._lock:
            logger = self._logger
            path = (
                logger.session_directory
                if logger is not None and logger.session_started
                else self._config.data_dir / "sessions"
            )
        self._open_folder(path)

    def session_summaries(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            logger = self._logger or JsonlSessionLogger(
                self._config.data_dir,
                model_version="desktop",
                configuration_version=self._config.configuration_version,
            )
            return logger.list_session_summaries()

    def save_diagnostic_setting(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise ValueError("diagnostic setting must be true or false")
        with self._lock:
            self._config = replace(
                load_config(self.config_path),
                save_diagnostic_frames=enabled,
            )
            write_config(self.config_path, self._config)

    @staticmethod
    def _open_folder(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            command = ("open", str(path))
        else:
            command = ("xdg-open", str(path))
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def delete_history(self) -> tuple[Path, ...]:
        self.stop()
        with self._lock:
            logger = self._logger or JsonlSessionLogger(
                self._config.data_dir,
                model_version="desktop",
                configuration_version=self._config.configuration_version,
            )
            removed = logger.delete_history()
            self._logger = None
            return removed

    def snapshot(self) -> DesktopSnapshot:
        with self._lock:
            now = datetime.now().astimezone()
            logger = self._logger
            if logger is None:
                logger = JsonlSessionLogger(
                    self._config.data_dir,
                    model_version="desktop",
                    configuration_version=self._config.configuration_version,
                )
            metrics = logger.snapshot(now.date(), now, time.monotonic())
            session_metrics = logger.session_snapshot(now, time.monotonic())
            running = self._thread is not None and self._thread.is_alive()
            return DesktopSnapshot(
                status=self._status,
                status_seconds=max(0.0, time.monotonic() - self._status_started),
                metrics=metrics,
                session_metrics=session_metrics,
                last_sample=self._last_sample,
                running=running,
                paused=self._runner.paused if running and self._runner is not None else True,
                error=self._error,
            )

    def _run_tracker(self, runner: TrackerRunner) -> None:
        try:
            runner.run()
        except Exception as error:
            with self._lock:
                self._error = str(error)
                self._set_status(DetectionResult(Status.CAMERA_ERROR, 1.0, str(error)))
        finally:
            with self._lock:
                instance_lock = self._instance_lock
                self._instance_lock = None
            if instance_lock is not None:
                instance_lock.release()

    def _set_status(self, result: DetectionResult) -> None:
        with self._lock:
            if result.status is not self._status:
                self._status = result.status
                self._status_started = time.monotonic()

    def _set_last_sample(self, sampled_at: datetime) -> None:
        with self._lock:
            self._last_sample = sampled_at

    def _set_diagnostic_error(self, message: str) -> None:
        with self._lock:
            self._error = f"Diagnostic output stopped: {message}. Tracking continues."

    @contextmanager
    def _camera_operation(self, name: str) -> Iterator[None]:
        if not self._camera_operation_lock.acquire(blocking=False):
            active = self._active_camera_operation or "another camera operation"
            raise DesktopBusyError(
                f"Cannot start {name} while {active} is active. Close it and try again."
            )
        self._active_camera_operation = name
        try:
            yield
        finally:
            self._active_camera_operation = None
            self._camera_operation_lock.release()
