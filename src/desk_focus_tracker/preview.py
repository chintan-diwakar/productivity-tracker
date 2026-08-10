from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any

from desk_focus_tracker.camera import OpenCVCamera, import_cv2
from desk_focus_tracker.config import AppConfig, load_config
from desk_focus_tracker.domain import DetectionResult
from desk_focus_tracker.mediapipe_detector import MediaPipeDetector
from desk_focus_tracker.vision import NormalizedBox, VisionEvidence


class PreviewError(RuntimeError):
    """Raised when OpenCV cannot show the diagnostic window."""


def evidence_lines(
    evidence: VisionEvidence,
    result: DetectionResult,
    config: AppConfig,
) -> tuple[str, ...]:
    person = _detected_text("PERSON", evidence.person_count, evidence.person_confidence)
    face = _detected_text("FACE", evidence.face_count)
    phone = _detected_text("PHONE", len(evidence.phone_boxes), evidence.phone_confidence)

    if not evidence.phone_boxes:
        hand = "HAND: NOT RUN (phone absent)"
    elif evidence.hand_points:
        hand = f"HAND: DETECTED ({len(evidence.hand_points)} points)"
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

    return (
        f"STATUS: {result.status.value}",
        person,
        face,
        phone,
        hand,
        head,
        f"REASON: {result.reason}",
        f"OBJECT THRESHOLD: {config.object_score_threshold:.2f}",
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
    lines = evidence_lines(evidence, result, config)
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
) -> int:
    if duration_seconds is not None and duration_seconds <= 0.0:
        raise ValueError("duration_seconds must be positive")
    if score_threshold is not None and not 0.0 <= score_threshold <= 1.0:
        raise ValueError("score_threshold must be between 0.0 and 1.0")

    config = load_config(config_path)
    if score_threshold is not None:
        config = replace(config, object_score_threshold=score_threshold)
    if config.detector_backend != "mediapipe":
        raise ValueError("the preview requires detector_backend=mediapipe")

    cv2 = import_cv2()
    camera = OpenCVCamera(config.camera_index, config.frame_width, config.frame_height)
    detector = MediaPipeDetector(config)
    window_name = "Desk Focus Diagnostic Preview"
    started = time.monotonic()
    next_sample = started
    camera_opened = False
    window_opened = False

    print("Preview controls: press Q or Esc to stop.", flush=True)
    try:
        camera.open()
        camera_opened = True
        try:
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            window_opened = True
        except cv2.error as error:
            raise PreviewError(f"cannot open the preview window: {error}") from error

        while True:
            now = time.monotonic()
            if duration_seconds is not None and now - started >= duration_seconds:
                break

            if now >= next_sample:
                frame = camera.read()
                evidence = detector.analyze(frame)
                result = detector.classify(evidence)
                output = draw_debug_overlay(frame, evidence, result, config, cv2)
                cv2.imshow(window_name, output)
                print(" | ".join(evidence_lines(evidence, result, config)), flush=True)
                next_sample = now + 1.0 / config.capture_fps

            key = cv2.waitKey(20) & 0xFF
            if key in {27, ord("q"), ord("Q")}:
                break
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break
    except cv2.error as error:
        raise PreviewError(f"cannot update the preview window: {error}") from error
    finally:
        detector.close()
        if camera_opened:
            camera.close()
        if window_opened:
            cv2.destroyWindow(window_name)
    return 0
