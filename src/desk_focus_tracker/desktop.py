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
from desk_focus_tracker.diagnostics import DiagnosticFrameWriter
from desk_focus_tracker.domain import DetectionResult, StatisticsCategory, Status
from desk_focus_tracker.idle import create_idle_monitor
from desk_focus_tracker.instance_lock import InstanceLock, data_directory_lock
from desk_focus_tracker.metrics import DailyMetrics, SessionMetrics, format_duration, format_ratio
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
        self.root.geometry("560x850")
        self.root.minsize(520, 760)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.status_value = tk.StringVar(value="Paused")
        self.status_duration = tk.StringVar(value="0s")
        self.session_value = tk.StringVar(value="No session")
        self.ratio_value = tk.StringVar(value="Not enough data")
        self.coverage_value = tk.StringVar(value="Not enough data")
        self.focused_value = tk.StringVar(value="0s")
        self.phone_value = tk.StringVar(value="0s")
        self.looking_down_value = tk.StringVar(value="0s")
        self.looking_away_value = tk.StringVar(value="0s")
        self.away_value = tk.StringVar(value="0s")
        self.uncertain_value = tk.StringVar(value="0s")
        self.idle_value = tk.StringVar(value="0s")
        self.paused_value = tk.StringVar(value="0s")
        self.camera_error_value = tk.StringVar(value="0s")
        self.today_value = tk.StringVar(value="Today: no classified time")
        self.last_sample_value = tk.StringVar(value="No successful sample")
        self.message_value = tk.StringVar(value="Tracking starts only when you select Start.")
        self.privacy_value = tk.StringVar(
            value="Normal tracking does not save images or audio."
        )
        self.camera_index_value = tk.StringVar(value=str(controller.config.camera_index))
        self.diagnostic_value = tk.BooleanVar(
            value=controller.config.save_diagnostic_frames
        )
        self._update_privacy_text()
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

        self.ttk.Label(
            frame,
            textvariable=self.session_value,
            font=("TkDefaultFont", 11, "bold"),
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self._metric(frame, 4, "Session focus ratio", self.ratio_value)
        self._metric(frame, 5, "Classified coverage", self.coverage_value)
        self._metric(frame, 6, "Focused", self.focused_value)
        self._metric(frame, 7, "Possible phone use", self.phone_value)
        self._metric(frame, 8, "Looking down", self.looking_down_value)
        self._metric(frame, 9, "Looking away", self.looking_away_value)
        self._metric(frame, 10, "Away (no person)", self.away_value)
        self._metric(frame, 11, "Uncertain", self.uncertain_value)
        self._metric(frame, 12, "System idle", self.idle_value)
        self._metric(frame, 13, "Paused", self.paused_value)
        self._metric(frame, 14, "Camera error", self.camera_error_value)

        self.ttk.Separator(frame).grid(row=15, column=0, columnspan=2, sticky="ew", pady=18)
        controls = self.ttk.Frame(frame)
        controls.grid(row=16, column=0, columnspan=2, sticky="ew")
        for column in range(4):
            controls.columnconfigure(column, weight=1)
        start_button = self.ttk.Button(controls, text="Start / Resume", command=self._start)
        start_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._action_buttons.append(start_button)
        self.ttk.Button(controls, text="Pause", command=self.controller.pause).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        self.ttk.Button(
            controls, text="Pause 15 min", command=lambda: self.controller.pause(900)
        ).grid(row=0, column=2, sticky="ew", padx=4)
        end_button = self.ttk.Button(controls, text="End session", command=self._end_session)
        end_button.grid(row=0, column=3, sticky="ew", padx=(4, 0))
        self._action_buttons.append(end_button)

        setup = self.ttk.LabelFrame(frame, text="Camera setup", padding=12)
        setup.grid(row=17, column=0, columnspan=2, sticky="ew", pady=(18, 0))
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
        privacy.grid(row=18, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        for column in range(3):
            privacy.columnconfigure(column, weight=1)
        self.ttk.Label(
            privacy,
            textvariable=self.privacy_value,
            wraplength=470,
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        diagnostic_toggle = self.ttk.Checkbutton(
            privacy,
            text="Save diagnostic output for the next session",
            variable=self.diagnostic_value,
            command=self._toggle_diagnostics,
        )
        diagnostic_toggle.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self._action_buttons.append(diagnostic_toggle)
        self.ttk.Button(
            privacy,
            text="Session history",
            command=self._show_session_history,
        ).grid(row=2, column=0, sticky="ew", padx=(0, 4), pady=(10, 0))
        self.ttk.Button(privacy, text="Open data folder", command=self._open_data).grid(
            row=2, column=1, sticky="ew", padx=4, pady=(10, 0)
        )
        self.ttk.Button(privacy, text="Delete history", command=self._delete_history).grid(
            row=2, column=2, sticky="ew", padx=(4, 0), pady=(10, 0)
        )

        self.ttk.Label(frame, textvariable=self.last_sample_value).grid(
            row=19, column=0, columnspan=2, sticky="w", pady=(18, 0)
        )
        self.ttk.Label(frame, textvariable=self.today_value).grid(
            row=20, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        self.ttk.Label(frame, textvariable=self.message_value, wraplength=460).grid(
            row=21, column=0, columnspan=2, sticky="w", pady=(6, 0)
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

    def _end_session(self) -> None:
        self._run_action("Ending session", self.controller.end_session)

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

    def _show_session_history(self) -> None:
        try:
            summaries = self.controller.session_summaries()
        except Exception as error:
            self.message_value.set(f"Cannot read session history: {error}")
            return

        window = self.tk.Toplevel(self.root)
        window.title("Session history")
        window.geometry("860x620")
        window.minsize(700, 500)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        frame = self.ttk.Frame(window, padding=16)
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        columns = ("started", "state", "duration", "focus", "phone")
        tree = self.ttk.Treeview(frame, columns=columns, show="headings", height=10)
        headings = {
            "started": "Started",
            "state": "State",
            "duration": "Duration",
            "focus": "Focus ratio",
            "phone": "Phone use",
        }
        widths = {"started": 180, "state": 80, "duration": 90, "focus": 90, "phone": 90}
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = self.ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        details = self.tk.Text(frame, height=18, wrap="word")
        details.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        details.configure(state="disabled")
        summaries_by_item: dict[str, dict[str, Any]] = {}
        for summary in summaries:
            started_at = datetime.fromisoformat(str(summary["started_at"]))
            statuses = summary.get("status_seconds", {})
            phone_seconds = float(statuses.get(Status.POSSIBLE_PHONE_USE.value, 0.0))
            item = tree.insert(
                "",
                "end",
                values=(
                    started_at.strftime("%Y-%m-%d %H:%M:%S"),
                    str(summary.get("state", "unknown")).title(),
                    format_duration(float(summary.get("tracked_seconds", 0.0))),
                    format_ratio(_optional_float(summary.get("focused_active_ratio"))),
                    format_duration(phone_seconds),
                ),
            )
            summaries_by_item[item] = summary

        def show_selected(_event: object | None = None) -> None:
            selection = tree.selection()
            if not selection:
                return
            summary = summaries_by_item[selection[0]]
            status_seconds = summary.get("status_seconds", {})
            lines = [
                f"Session: {summary.get('session_id', 'unknown')}",
                f"Started: {summary.get('started_at', 'unknown')}",
                f"Ended: {summary.get('ended_at') or 'Active'}",
                f"Final status: {summary.get('final_status', 'unknown')}",
                f"Final reason: {summary.get('final_reason', 'unknown')}",
                f"Transitions: {summary.get('transition_count', 0)}",
                "Diagnostic images: "
                f"{summary.get('diagnostic_frame_count', 0)} "
                f"(enabled: {summary.get('diagnostic_output_enabled', False)})",
                "",
                "Status durations:",
            ]
            for status in Status:
                seconds = float(status_seconds.get(status.value, 0.0))
                lines.append(f"  {STATUS_LABELS[status]}: {format_duration(seconds)}")
            details.configure(state="normal")
            details.delete("1.0", self.tk.END)
            details.insert("1.0", "\n".join(lines))
            details.configure(state="disabled")

        tree.bind("<<TreeviewSelect>>", show_selected)
        items = tree.get_children()
        if items:
            tree.selection_set(items[0])
            show_selected()
        else:
            details.configure(state="normal")
            details.insert("1.0", "No saved sessions.")
            details.configure(state="disabled")

    def _toggle_diagnostics(self) -> None:
        enabled = bool(self.diagnostic_value.get())
        if enabled:
            confirmed = self.messagebox.askyesno(
                "Save diagnostic output",
                "Diagnostic images can show you, other people, and your room. "
                "Save sampled images for the next session?",
            )
            if not confirmed:
                self.diagnostic_value.set(False)
                self._update_privacy_text()
                return
        try:
            self.controller.save_diagnostic_setting(enabled)
        except Exception as error:
            self.diagnostic_value.set(not enabled)
            self.message_value.set(f"Diagnostic setting failed: {error}")
        else:
            state = "enabled" if enabled else "disabled"
            self.message_value.set(
                f"Diagnostic output is {state}. The change applies to the next session."
            )
        self._update_privacy_text()

    def _update_privacy_text(self) -> None:
        self.privacy_value.set(
            "Sampled diagnostic images stay on this computer. The next session saves images."
            if self.diagnostic_value.get()
            else "Normal tracking does not save images or audio."
        )

    def _delete_history(self) -> None:
        confirmed = self.messagebox.askyesno(
            "Delete local history",
            "Delete all local events, session summaries, and diagnostic images? "
            "This action cannot be undone.",
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
            self._set_session_metrics(snapshot.session_metrics)
            categories = snapshot.metrics.category_seconds
            daily_focused = categories[StatisticsCategory.PRODUCTIVE.value]
            daily_phone = categories[StatisticsCategory.UNPRODUCTIVE.value]
            self.today_value.set(
                "Today: "
                f"Focused {format_duration(daily_focused)} · "
                f"Phone {format_duration(daily_phone)} · "
                f"Coverage {format_ratio(snapshot.metrics.classified_coverage)}"
            )
            self.last_sample_value.set(
                "No successful camera sample"
                if snapshot.last_sample is None
                else f"Last camera sample: {snapshot.last_sample.strftime('%H:%M:%S')}"
            )
            if snapshot.error:
                self.message_value.set(snapshot.error)
        self.root.after(1000, self._refresh)

    def _set_session_metrics(self, metrics: SessionMetrics | None) -> None:
        if metrics is None:
            self.session_value.set("No session. Select Start / Resume to create one.")
            self.ratio_value.set("Not enough data")
            self.coverage_value.set("Not enough data")
            status_seconds = {status.value: 0.0 for status in Status}
        else:
            state = "Active" if metrics.active else "Ended"
            diagnostics = (
                f" · {metrics.diagnostic_frame_count} diagnostic images"
                if metrics.diagnostic_output_enabled
                else ""
            )
            self.session_value.set(
                f"Session {metrics.session_id[:8]} · {state} · "
                f"Started {metrics.started_at.strftime('%H:%M:%S')}{diagnostics}"
            )
            self.ratio_value.set(format_ratio(metrics.focused_active_ratio))
            self.coverage_value.set(format_ratio(metrics.classified_coverage))
            status_seconds = metrics.status_seconds

        self.focused_value.set(format_duration(status_seconds[Status.FOCUSED_SCREEN.value]))
        self.phone_value.set(format_duration(status_seconds[Status.POSSIBLE_PHONE_USE.value]))
        self.looking_down_value.set(format_duration(status_seconds[Status.LOOKING_DOWN.value]))
        self.looking_away_value.set(format_duration(status_seconds[Status.LOOKING_AWAY.value]))
        self.away_value.set(format_duration(status_seconds[Status.AWAY.value]))
        self.uncertain_value.set(format_duration(status_seconds[Status.UNCERTAIN.value]))
        self.idle_value.set(format_duration(status_seconds[Status.SYSTEM_IDLE.value]))
        self.paused_value.set(format_duration(status_seconds[Status.PAUSED.value]))
        self.camera_error_value.set(format_duration(status_seconds[Status.CAMERA_ERROR.value]))

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
