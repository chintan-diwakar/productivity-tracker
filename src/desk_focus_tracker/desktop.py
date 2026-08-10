from __future__ import annotations

import queue
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

from desk_focus_tracker.calibration import CalibrationResult, calibrate_neutral_head
from desk_focus_tracker.camera import OpenCVCamera
from desk_focus_tracker.config import (
    AppConfig,
    default_config_path,
    load_config,
    write_config,
    write_default_config,
)
from desk_focus_tracker.detector import create_detector
from desk_focus_tracker.domain import DetectionResult, StatisticsCategory, Status
from desk_focus_tracker.idle import create_idle_monitor
from desk_focus_tracker.instance_lock import InstanceLock, data_directory_lock
from desk_focus_tracker.metrics import DailyMetrics, format_duration, format_ratio
from desk_focus_tracker.models import ModelStore
from desk_focus_tracker.preview import run_preview
from desk_focus_tracker.runner import TrackerRunner
from desk_focus_tracker.storage import JsonlSessionLogger


class DesktopDependencyError(RuntimeError):
    """Raised when the desktop UI dependency is not installed."""


class DesktopBusyError(RuntimeError):
    """Raised when two operations try to use the camera at the same time."""


STATUS_LABELS = {
    Status.FOCUSED_SCREEN: "Focused",
    Status.POSSIBLE_PHONE_USE: "Possible phone use",
    Status.LOOKING_DOWN: "Looking down · uncertain",
    Status.LOOKING_AWAY: "Looking away · uncertain",
    Status.AWAY: "Away",
    Status.SYSTEM_IDLE: "System idle",
    Status.UNCERTAIN: "Uncertain",
    Status.PAUSED: "Paused",
    Status.CAMERA_ERROR: "Camera error",
}


@dataclass(frozen=True, slots=True)
class DesktopSnapshot:
    status: Status
    status_seconds: float
    metrics: DailyMetrics
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
                )
                runner = TrackerRunner(
                    config,
                    camera,
                    detector,
                    logger,
                    status_callback=self._set_status,
                    sample_callback=self._set_last_sample,
                    idle_monitor=create_idle_monitor(),
                )
            except Exception:
                instance_lock.release()
                raise
            self._config = config
            self._logger = logger
            self._runner = runner
            self._instance_lock = instance_lock
            self._error = None
            self._thread = threading.Thread(
                target=self._run_tracker,
                args=(runner,),
                name="desk-focus-tracker",
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
        path = self.config.data_dir
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
            running = self._thread is not None and self._thread.is_alive()
            return DesktopSnapshot(
                status=self._status,
                status_seconds=max(0.0, time.monotonic() - self._status_started),
                metrics=metrics,
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


class DeskFocusWindow:
    def __init__(self, controller: DesktopController, tk: Any, ttk: Any, messagebox: Any) -> None:
        self.controller = controller
        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.actions: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
        self._action_in_progress = False
        self._action_buttons: list[Any] = []
        self.root = tk.Tk()
        self.root.title("Desk Focus Tracker")
        self.root.geometry("520x650")
        self.root.minsize(480, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.status_value = tk.StringVar(value="Paused")
        self.status_duration = tk.StringVar(value="0s")
        self.ratio_value = tk.StringVar(value="Not enough data")
        self.coverage_value = tk.StringVar(value="Not enough data")
        self.focused_value = tk.StringVar(value="0s")
        self.phone_value = tk.StringVar(value="0s")
        self.uncertain_value = tk.StringVar(value="0s")
        self.excluded_value = tk.StringVar(value="0s")
        self.last_sample_value = tk.StringVar(value="No successful sample")
        self.message_value = tk.StringVar(value="Tracking starts only when you select Start.")
        self.camera_index_value = tk.StringVar(value=str(controller.config.camera_index))
        self._build()
        self.root.after(200, self._refresh)

    def _build(self) -> None:
        root = self.root
        root.columnconfigure(0, weight=1)
        frame = self.ttk.Frame(root, padding=24)
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        self.ttk.Label(frame, text="Current status", font=("TkDefaultFont", 11)).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self.ttk.Label(
            frame, textvariable=self.status_value, font=("TkDefaultFont", 24, "bold")
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.ttk.Label(frame, textvariable=self.status_duration).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(0, 20)
        )

        self._metric(frame, 3, "Focused active time", self.ratio_value)
        self._metric(frame, 4, "Classified coverage", self.coverage_value)
        self._metric(frame, 5, "Focused", self.focused_value)
        self._metric(frame, 6, "Possible phone use", self.phone_value)
        self._metric(frame, 7, "Uncertain", self.uncertain_value)
        self._metric(frame, 8, "Away and excluded", self.excluded_value)

        self.ttk.Separator(frame).grid(row=9, column=0, columnspan=2, sticky="ew", pady=18)
        controls = self.ttk.Frame(frame)
        controls.grid(row=10, column=0, columnspan=2, sticky="ew")
        for column in range(3):
            controls.columnconfigure(column, weight=1)
        start_button = self.ttk.Button(controls, text="Start / Resume", command=self._start)
        start_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self._action_buttons.append(start_button)
        self.ttk.Button(controls, text="Pause", command=self.controller.pause).grid(
            row=0, column=1, sticky="ew", padx=5
        )
        self.ttk.Button(
            controls, text="Pause 15 min", command=lambda: self.controller.pause(900)
        ).grid(row=0, column=2, sticky="ew", padx=(5, 0))

        setup = self.ttk.LabelFrame(frame, text="Camera setup", padding=12)
        setup.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        setup.columnconfigure(1, weight=1)
        self.ttk.Label(setup, text="Camera index").grid(row=0, column=0, sticky="w")
        self.ttk.Spinbox(
            setup,
            from_=0,
            to=20,
            textvariable=self.camera_index_value,
            width=8,
        ).grid(row=0, column=1, sticky="w", padx=8)
        save_button = self.ttk.Button(setup, text="Save", command=self._save_camera)
        save_button.grid(row=0, column=2, sticky="e")
        download_button = self.ttk.Button(
            setup, text="Download models", command=self._download_models
        )
        download_button.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        preview_button = self.ttk.Button(setup, text="Camera preview", command=self._preview)
        preview_button.grid(row=1, column=1, sticky="ew", padx=8, pady=(10, 0))
        calibrate_button = self.ttk.Button(setup, text="Calibrate", command=self._calibrate)
        calibrate_button.grid(row=1, column=2, sticky="ew", pady=(10, 0))
        self._action_buttons.extend(
            (save_button, download_button, preview_button, calibrate_button)
        )

        privacy = self.ttk.LabelFrame(frame, text="Privacy", padding=12)
        privacy.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        privacy.columnconfigure(0, weight=1)
        privacy.columnconfigure(1, weight=1)
        self.ttk.Label(
            privacy,
            text="Frames stay on this computer. The application does not save images or audio.",
            wraplength=430,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.ttk.Button(privacy, text="Open data folder", command=self._open_data).grid(
            row=1, column=0, sticky="ew", padx=(0, 4), pady=(10, 0)
        )
        self.ttk.Button(privacy, text="Delete history", command=self._delete_history).grid(
            row=1, column=1, sticky="ew", padx=(4, 0), pady=(10, 0)
        )

        self.ttk.Label(frame, textvariable=self.last_sample_value).grid(
            row=13, column=0, columnspan=2, sticky="w", pady=(18, 0)
        )
        self.ttk.Label(frame, textvariable=self.message_value, wraplength=460).grid(
            row=14, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

    def _metric(self, parent: Any, row: int, label: str, value: Any) -> None:
        self.ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        self.ttk.Label(parent, textvariable=value, font=("TkDefaultFont", 11, "bold")).grid(
            row=row, column=1, sticky="e", pady=3
        )

    def _run_action(self, name: str, action: Any) -> None:
        if self._action_in_progress:
            self.message_value.set(
                "Close the current camera window before starting another action."
            )
            return
        self._action_in_progress = True
        self._set_action_buttons_enabled(False)
        self.message_value.set(f"{name}…")

        def run() -> None:
            try:
                result = action()
            except Exception as error:
                self.actions.put(("error", f"{name} failed: {error}"))
            else:
                self.actions.put(("success", (name, result)))

        threading.Thread(target=run, name=f"desktop-{name}", daemon=True).start()

    def _start(self) -> None:
        if self._save_camera():
            self._run_action("Starting tracking", self.controller.start)

    def _download_models(self) -> None:
        self._run_action("Downloading models", self.controller.download_models)

    def _preview(self) -> None:
        if self._save_camera():
            self._run_action("Opening preview", self.controller.preview)

    def _calibrate(self) -> None:
        if not self._save_camera():
            return
        self.messagebox.showinfo(
            "Calibration",
            "Face the main screen and keep your head still until calibration is complete.",
        )
        self._run_action("Calibrating", self.controller.calibrate)

    def _save_camera(self) -> bool:
        if self._action_in_progress:
            self.message_value.set("Close the current camera window before changing settings.")
            return False
        try:
            self.controller.save_camera_index(int(self.camera_index_value.get()))
        except (TypeError, ValueError) as error:
            self.message_value.set(f"Camera setting failed: {error}")
            return False
        return True

    def _open_data(self) -> None:
        try:
            self.controller.open_data_folder()
        except Exception as error:
            self.message_value.set(f"Cannot open the data folder: {error}")

    def _delete_history(self) -> None:
        confirmed = self.messagebox.askyesno(
            "Delete local history",
            "Delete all local event and summary files? This action cannot be undone.",
        )
        if confirmed:
            self._run_action("Deleting history", self.controller.delete_history)

    def _refresh(self) -> None:
        while True:
            try:
                outcome, payload = self.actions.get_nowait()
            except queue.Empty:
                break
            self._action_in_progress = False
            self._set_action_buttons_enabled(True)
            if outcome == "error":
                self.message_value.set(str(payload))
            else:
                name, result = payload
                if isinstance(result, CalibrationResult):
                    self.message_value.set(
                        "Calibration complete. Neutral head angle: "
                        f"{result.neutral_pitch_degrees:.1f}°."
                    )
                elif name == "Opening preview":
                    self.message_value.set("Preview closed. Select Start / Resume to track.")
                else:
                    self.message_value.set(f"{name} complete.")

        try:
            snapshot = self.controller.snapshot()
        except Exception as error:
            self.message_value.set(f"Cannot read daily metrics: {error}")
        else:
            self.status_value.set(STATUS_LABELS[snapshot.status])
            self.status_duration.set(format_duration(snapshot.status_seconds))
            self.ratio_value.set(format_ratio(snapshot.metrics.focused_active_ratio))
            self.coverage_value.set(format_ratio(snapshot.metrics.classified_coverage))
            categories = snapshot.metrics.category_seconds
            self.focused_value.set(format_duration(categories[StatisticsCategory.PRODUCTIVE.value]))
            self.phone_value.set(format_duration(categories[StatisticsCategory.UNPRODUCTIVE.value]))
            self.uncertain_value.set(
                format_duration(categories[StatisticsCategory.UNCERTAIN.value])
            )
            self.excluded_value.set(format_duration(categories[StatisticsCategory.EXCLUDED.value]))
            self.last_sample_value.set(
                "No successful camera sample"
                if snapshot.last_sample is None
                else f"Last camera sample: {snapshot.last_sample.strftime('%H:%M:%S')}"
            )
            if snapshot.error:
                self.message_value.set(snapshot.error)
        self.root.after(1000, self._refresh)

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in self._action_buttons:
            button.configure(state=state)

    def quit(self) -> None:
        self.controller.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def _import_tkinter() -> tuple[Any, Any, Any]:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError as error:
        raise DesktopDependencyError(
            "Tk is not installed. Install python3-tk, then start the application again."
        ) from error
    return tk, ttk, messagebox


def run_desktop(config_path: Path | None = None) -> int:
    tk, ttk, messagebox = _import_tkinter()
    controller = DesktopController(config_path)
    DeskFocusWindow(controller, tk, ttk, messagebox).run()
    return 0


def main() -> int:
    try:
        return run_desktop()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
