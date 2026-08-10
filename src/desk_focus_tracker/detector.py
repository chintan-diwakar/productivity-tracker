from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from desk_focus_tracker.camera import DependencyError, import_cv2
from desk_focus_tracker.config import AppConfig
from desk_focus_tracker.domain import DetectionResult, Status


class Detector(Protocol):
    model_version: str

    def detect(self, frame: Any) -> DetectionResult: ...

    def close(self) -> None: ...


class OpenCVFaceDetector:
    """Prototype detector based on OpenCV frontal-face presence."""

    model_version = "opencv-haar-frontalface-v1"

    def __init__(self) -> None:
        cv2 = import_cv2()
        cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(str(cascade_path))
        if cascade.empty():
            raise DependencyError(f"cannot load OpenCV face cascade: {cascade_path}")
        self._cv2 = cv2
        self._cascade = cascade

    def detect(self, frame: Any) -> DetectionResult:
        gray = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2GRAY)
        minimum_side = max(24, min(gray.shape[:2]) // 8)
        faces = self._cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(minimum_side, minimum_side),
        )

        face_count = len(faces)
        if face_count == 0:
            return DetectionResult(Status.AWAY, 0.70, "no_frontal_face_detected")
        if face_count > 1:
            return DetectionResult(Status.UNCERTAIN, 0.20, "multiple_faces_detected")
        return DetectionResult(Status.FOCUSED_SCREEN, 0.60, "one_frontal_face_detected")

    def close(self) -> None:
        return None


def create_detector(config: AppConfig) -> Detector:
    if config.detector_backend == "mediapipe":
        from desk_focus_tracker.mediapipe_detector import MediaPipeDetector

        return MediaPipeDetector(config)
    if config.detector_backend == "opencv_face":
        return OpenCVFaceDetector()
    raise ValueError(f"unsupported detector backend: {config.detector_backend}")
