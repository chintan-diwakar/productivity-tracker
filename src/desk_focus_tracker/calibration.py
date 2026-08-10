from __future__ import annotations

import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from desk_focus_tracker.camera import OpenCVCamera
from desk_focus_tracker.config import AppConfig
from desk_focus_tracker.mediapipe_detector import MediaPipeDetector


class CalibrationError(RuntimeError):
    """Raised when calibration cannot get enough face samples."""


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    config: AppConfig
    neutral_pitch_degrees: float
    samples: int
    spread_degrees: float


def calculate_neutral_pitch(pitches: Sequence[float]) -> tuple[float, float]:
    if len(pitches) < 3:
        raise CalibrationError("calibration requires at least three face samples")
    neutral = float(statistics.median(pitches))
    deviations = [abs(value - neutral) for value in pitches]
    spread = float(statistics.median(deviations))
    return neutral, spread


def calibrate_neutral_head(
    config: AppConfig,
    *,
    sample_count: int = 10,
    sample_interval_seconds: float = 0.2,
    progress_callback: Callable[[int, int], None] | None = None,
) -> CalibrationResult:
    if sample_count < 3:
        raise ValueError("sample_count must be at least three")
    if sample_interval_seconds <= 0.0:
        raise ValueError("sample_interval_seconds must be positive")

    camera = OpenCVCamera(config.camera_index, config.frame_width, config.frame_height)
    detector = MediaPipeDetector(config)
    progress_callback = progress_callback or (lambda _current, _total: None)
    pitches: list[float] = []
    attempts = 0
    maximum_attempts = sample_count * 3
    try:
        camera.open()
        while len(pitches) < sample_count and attempts < maximum_attempts:
            attempts += 1
            evidence = detector.analyze(camera.read())
            if evidence.face_count == 1 and evidence.head_pitch_degrees is not None:
                pitches.append(evidence.head_pitch_degrees)
                progress_callback(len(pitches), sample_count)
            if len(pitches) < sample_count:
                time.sleep(sample_interval_seconds)
    finally:
        detector.close()
        camera.close()

    neutral, spread = calculate_neutral_pitch(pitches)
    if spread > 8.0:
        raise CalibrationError("head movement was too large during calibration")
    return CalibrationResult(
        config=replace(config, neutral_head_pitch_degrees=neutral),
        neutral_pitch_degrees=neutral,
        samples=len(pitches),
        spread_degrees=spread,
    )
