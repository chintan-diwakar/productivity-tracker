from __future__ import annotations

import math
import threading
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from know_your_focus.camera import CameraProperties, OpenCVCamera, import_cv2
from know_your_focus.config import AppConfig, load_config
from know_your_focus.domain import DetectionResult, Status
from know_your_focus.mediapipe_detector import MediaPipeDetector
from know_your_focus.vision import NormalizedBox, VisionEvidence


class PreviewError(RuntimeError):
    """Raised when OpenCV cannot show the diagnostic window."""


class EvidenceDetector(Protocol):
    def analyze(self, frame: Any) -> VisionEvidence: ...

    def classify(self, evidence: VisionEvidence) -> DetectionResult: ...


@dataclass(frozen=True, slots=True)
class InferenceSnapshot:
    sequence: int
    evidence: VisionEvidence
    result: DetectionResult
    latency_ms: float
    completed_at: float


@dataclass(frozen=True, slots=True)
class PreviewPerformance:
    camera: CameraProperties
    target_display_fps: float
    measured_display_fps: float
    target_inference_fps: float
    inference_latency_ms: float | None


class InferenceWorker:
    """Process only the newest submitted frame on one background thread."""

    def __init__(self, detector: EvidenceDetector) -> None:
        self._detector = detector
        self._condition = threading.Condition()
        self._pending_frame: Any | None = None
        self._latest: InferenceSnapshot | None = None
        self._error: Exception | None = None
        self._stopping = False
        self._sequence = 0
        self._thread = threading.Thread(
            target=self._run,
            name="desk-focus-inference",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def submit(self, frame: Any) -> None:
        with self._condition:
            if self._stopping:
                return
            self._pending_frame = frame
            self._condition.notify()

    def latest(self) -> InferenceSnapshot | None:
        with self._condition:
            return self._latest

    def error(self) -> Exception | None:
        with self._condition:
            return self._error

    def wait_for_snapshot(self, timeout: float) -> InferenceSnapshot | None:
        with self._condition:
            self._condition.wait_for(
                lambda: self._latest is not None or self._error is not None,
                timeout=timeout,
            )
            return self._latest

    def stop(self) -> None:
        with self._condition:
            self._stopping = True
            self._pending_frame = None
            self._condition.notify_all()
        if self._thread.is_alive():
            self._thread.join()

    def _run(self) -> None:
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(
                        lambda: self._stopping or self._pending_frame is not None
                    )
                    if self._stopping:
                        return
                    frame = self._pending_frame
                    self._pending_frame = None

                started = time.perf_counter()
                evidence = self._detector.analyze(frame)
                result = self._detector.classify(evidence)
                latency_ms = (time.perf_counter() - started) * 1000
                with self._condition:
                    self._sequence += 1
                    self._latest = InferenceSnapshot(
                        sequence=self._sequence,
                        evidence=evidence,
                        result=result,
                        latency_ms=latency_ms,
                        completed_at=time.monotonic(),
                    )
                    self._condition.notify_all()
        except Exception as error:
            with self._condition:
                self._error = error
                self._stopping = True
                self._condition.notify_all()


def evidence_lines(
    evidence: VisionEvidence,
    result: DetectionResult,
    config: AppConfig,
    performance: PreviewPerformance | None = None,
) -> tuple[str, ...]:
    person = _detected_text("PERSON", evidence.person_count, evidence.person_confidence)
    face = _detected_text("FACE", evidence.face_count)
    phone = _detected_text("PHONE", len(evidence.phone_boxes), evidence.phone_confidence)

    if not evidence.phone_boxes:
        hand = "HAND: NOT RUN (phone absent)"
    elif evidence.hand_points:
        hand_count = max(1, math.ceil(len(evidence.hand_points) / 21))
        hand_label = "hand" if hand_count == 1 else "hands"
        point_label = "point" if len(evidence.hand_points) == 1 else "points"
        hand = (
            f"HAND: DETECTED ({hand_count} {hand_label}, {len(evidence.hand_points)} {point_label})"
        )
    else:
        hand = "HAND: NOT DETECTED"

    if evidence.head_pitch_degrees is None:
        head = "HEAD DOWN: UNKNOWN"
    else:
        relative_pitch = config.head_pitch_sign * (
            evidence.head_pitch_degrees - config.neutral_head_pitch_degrees
        )
        head_state = "YES" if relative_pitch >= config.downward_pitch_threshold_degrees else "NO"
        head = f"HEAD DOWN: {head_state} ({evidence.head_pitch_degrees:.1f} deg)"

    lines = (
        f"STATUS: {result.status.value}",
        person,
        face,
        phone,
        hand,
        head,
        f"REASON: {result.reason}",
        f"PHONE THRESHOLD: {config.object_score_threshold:.2f}",
        f"PERSON THRESHOLD: {config.person_score_threshold:.2f}",
    )
    if performance is None:
        return lines

    latency = (
        f"{performance.inference_latency_ms:.1f} ms"
        if performance.inference_latency_ms is not None
        else "waiting"
    )
    return lines + (
        f"CAMERA: {performance.camera.width}x{performance.camera.height}"
        f" (driver {performance.camera.fps:.1f} FPS)",
        (
            f"ZOOM: {performance.camera.zoom:.0f} (widest)"
            if performance.camera.zoom_supported and performance.camera.zoom == 0.0
            else f"ZOOM: {performance.camera.zoom:.0f}"
            if performance.camera.zoom_supported
            else "ZOOM: NOT SUPPORTED"
        ),
        f"DISPLAY: {performance.measured_display_fps:.1f}"
        f" / {performance.target_display_fps:.1f} FPS",
        f"INFERENCE: {latency} / {performance.target_inference_fps:.1f} FPS target",
    )


def _detected_text(label: str, count: int, confidence: float | None = None) -> str:
    if count == 0:
        return f"{label}: NOT DETECTED"
    confidence_text = f", score {confidence:.2f}" if confidence is not None else ""
    return f"{label}: DETECTED ({count}{confidence_text})"


def pixel_box(box: NormalizedBox, width: int, height: int) -> tuple[int, int, int, int]:
    x1 = round(max(0.0, min(1.0, box.x)) * width)
    y1 = round(max(0.0, min(1.0, box.y)) * height)
    x2 = round(max(0.0, min(1.0, box.x + box.width)) * width)
    y2 = round(max(0.0, min(1.0, box.y + box.height)) * height)
    return x1, y1, x2, y2


def draw_debug_overlay(
    frame: Any,
    evidence: VisionEvidence,
    result: DetectionResult,
    config: AppConfig,
    cv2: ModuleType | None = None,
    performance: PreviewPerformance | None = None,
) -> Any:
    cv2 = cv2 or import_cv2()
    camera_view = frame.copy()
    height, width = camera_view.shape[:2]

    for box in evidence.person_boxes:
        _draw_box(camera_view, box, "person", (70, 210, 70), cv2)
    for box in evidence.face_boxes:
        _draw_box(camera_view, box, "face", (220, 210, 60), cv2)
    for box in evidence.phone_boxes:
        _draw_box(camera_view, box, "phone", (40, 140, 255), cv2)
    for point in evidence.hand_points:
        center = (round(point.x * width), round(point.y * height))
        cv2.circle(camera_view, center, 2, (255, 80, 220), -1)

    display_height = max(480, height)
    display_width = round(width * display_height / height)
    if (display_width, display_height) != (width, height):
        camera_view = cv2.resize(
            camera_view,
            (display_width, display_height),
            interpolation=cv2.INTER_LINEAR,
        )

    panel_width = 440
    output = cv2.copyMakeBorder(
        camera_view,
        0,
        0,
        0,
        panel_width,
        cv2.BORDER_CONSTANT,
        value=(24, 24, 24),
    )
    lines = evidence_lines(evidence, result, config, performance)
    for index, line in enumerate(lines):
        y = 40 + index * 48
        if y >= display_height:
            break
        cv2.putText(
            output,
            line,
            (display_width + 16, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    return output


def resize_for_inference(frame: Any, config: AppConfig, cv2: ModuleType) -> Any:
    height, width = frame.shape[:2]
    scale = min(config.frame_width / width, config.frame_height / height, 1.0)
    if scale >= 1.0:
        return frame.copy()
    target_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)


def _window_is_visible(cv2: ModuleType, window_name: str) -> bool:
    try:
        return cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) >= 1
    except cv2.error:
        # Some OpenCV backends remove the GUI receiver as soon as the user closes
        # the window. In that state, asking for its properties raises an error.
        return False


def _destroy_window_safely(cv2: ModuleType, window_name: str) -> None:
    # The window may already have been destroyed by the desktop environment.
    with suppress(cv2.error):
        cv2.destroyWindow(window_name)


def _draw_box(
    frame: Any,
    box: NormalizedBox,
    label: str,
    color: tuple[int, int, int],
    cv2: ModuleType,
) -> None:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = pixel_box(box, width, height)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    cv2.putText(
        frame,
        label,
        (x1, max(15, y1 - 5)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        color,
        2,
        cv2.LINE_AA,
    )


def run_preview(
    config_path: Path | None,
    duration_seconds: float | None,
    score_threshold: float | None,
    preview_width: int,
    preview_height: int,
    display_fps: float,
    inference_fps: float,
    zoom: float,
) -> int:
    if duration_seconds is not None and duration_seconds <= 0.0:
        raise ValueError("duration_seconds must be positive")
    if score_threshold is not None and not 0.0 <= score_threshold <= 1.0:
        raise ValueError("score_threshold must be between 0.0 and 1.0")
    if preview_width <= 0 or preview_height <= 0:
        raise ValueError("preview dimensions must be positive")
    if not 0.0 < display_fps <= 120.0:
        raise ValueError("display_fps must be greater than 0.0 and not more than 120.0")
    if not 0.0 < inference_fps <= display_fps:
        raise ValueError("inference_fps must be positive and not more than display_fps")
    if zoom < 0.0:
        raise ValueError("zoom must be zero or greater")

    config = load_config(config_path)
    if score_threshold is not None:
        config = replace(config, object_score_threshold=score_threshold)
    if config.detector_backend != "mediapipe":
        raise ValueError("the preview requires detector_backend=mediapipe")

    cv2 = import_cv2()
    camera = OpenCVCamera(
        config.camera_index,
        preview_width,
        preview_height,
        capture_fps=display_fps,
        prefer_mjpeg=True,
        zoom=zoom,
    )
    detector = MediaPipeDetector(config)
    worker = InferenceWorker(detector)
    window_name = "Desk Focus Diagnostic Preview"
    started = time.monotonic()
    next_inference = started
    frame_times: deque[float] = deque(maxlen=max(2, round(display_fps * 2)))
    latest_snapshot: InferenceSnapshot | None = None
    last_printed_sequence = 0
    camera_opened = False
    window_opened = False
    worker_started = False

    print("Preview controls: press Q or Esc to stop.", flush=True)
    try:
        camera.open()
        camera_opened = True
        camera_properties = camera.properties()
        worker.start()
        worker_started = True
        try:
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            window_opened = True
        except cv2.error as error:
            raise PreviewError(f"cannot open the preview window: {error}") from error

        while True:
            frame_started = time.monotonic()
            now = time.monotonic()
            if duration_seconds is not None and now - started >= duration_seconds:
                break

            frame = camera.read()
            captured_at = time.monotonic()
            frame_times.append(captured_at)
            if captured_at >= next_inference:
                worker.submit(resize_for_inference(frame, config, cv2))
                next_inference = captured_at + 1.0 / inference_fps

            worker_error = worker.error()
            if worker_error is not None:
                raise PreviewError(f"inference failed: {worker_error}") from worker_error
            snapshot = worker.latest()
            if snapshot is not None:
                latest_snapshot = snapshot

            if latest_snapshot is None:
                evidence = VisionEvidence(0, 0.0, (), 0.0, 0, (), None)
                result = DetectionResult(
                    status=Status.UNCERTAIN,
                    confidence=0.0,
                    reason="waiting_for_first_inference",
                )
                inference_latency_ms = None
            else:
                evidence = latest_snapshot.evidence
                result = latest_snapshot.result
                inference_latency_ms = latest_snapshot.latency_ms

            measured_display_fps = 0.0
            if len(frame_times) > 1:
                measured_display_fps = (len(frame_times) - 1) / (frame_times[-1] - frame_times[0])
            performance = PreviewPerformance(
                camera=camera_properties,
                target_display_fps=display_fps,
                measured_display_fps=measured_display_fps,
                target_inference_fps=inference_fps,
                inference_latency_ms=inference_latency_ms,
            )
            output = draw_debug_overlay(
                frame,
                evidence,
                result,
                config,
                cv2,
                performance,
            )
            cv2.imshow(window_name, output)

            if latest_snapshot is not None and latest_snapshot.sequence != last_printed_sequence:
                print(
                    " | ".join(evidence_lines(evidence, result, config, performance)),
                    flush=True,
                )
                last_printed_sequence = latest_snapshot.sequence

            frame_elapsed = time.monotonic() - frame_started
            wait_ms = max(1, round(max(0.0, 1.0 / display_fps - frame_elapsed) * 1000))
            key = cv2.waitKey(wait_ms) & 0xFF
            if key in {27, ord("q"), ord("Q")}:
                break
            if not _window_is_visible(cv2, window_name):
                break
    except KeyboardInterrupt:
        print("Preview stopped.", flush=True)
    except cv2.error as error:
        raise PreviewError(f"cannot update the preview window: {error}") from error
    finally:
        if worker_started:
            worker.stop()
        detector.close()
        if camera_opened:
            camera.close()
        if window_opened:
            _destroy_window_safely(cv2, window_name)
    return 0
