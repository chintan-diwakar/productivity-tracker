from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from desk_focus_tracker.camera import import_cv2
from desk_focus_tracker.domain import DetectionResult


class DiagnosticCaptureError(RuntimeError):
    """Raised when the application cannot save diagnostic output."""


class DiagnosticFrameWriter:
    """Save bounded, annotated inference frames and an evidence manifest."""

    schema_version = 1

    def __init__(self, session_directory: Path, frame_limit: int) -> None:
        if frame_limit <= 0:
            raise ValueError("frame_limit must be positive")
        self._directory = session_directory / "diagnostics"
        self._manifest_path = self._directory / "manifest.jsonl"
        self._frame_limit = frame_limit
        self._frame_count = 0
        self._prepared = False

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def limit_reached(self) -> bool:
        return self._frame_count >= self._frame_limit

    def capture(
        self,
        frame: Any,
        result: DetectionResult,
        captured_at: datetime,
    ) -> bool:
        if self.limit_reached:
            return False
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise DiagnosticCaptureError("diagnostic timestamps must include a UTC offset")
        self._prepare_directory()
        cv2 = import_cv2()
        image = frame.copy()
        self._add_result_text(image, result, cv2)
        ok, encoded = cv2.imencode(".jpg", image, (cv2.IMWRITE_JPEG_QUALITY, 85))
        if not ok:
            raise DiagnosticCaptureError("OpenCV could not encode a diagnostic image")

        sequence = self._frame_count + 1
        timestamp = captured_at.strftime("%Y%m%dT%H%M%S-%f%z")
        filename = f"{sequence:06d}-{timestamp}-{result.status.value}.jpg"
        image_path = self._directory / filename
        try:
            descriptor = os.open(image_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded.tobytes())
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise DiagnosticCaptureError(
                f"cannot write diagnostic image {image_path}: {error}"
            ) from error

        manifest_record = {
            "schema_version": self.schema_version,
            "timestamp": captured_at.isoformat(),
            "image": filename,
            "status": result.status.value,
            "confidence": result.confidence,
            "reason": result.reason,
            "metrics": dict(result.metrics),
        }
        try:
            encoded_record = (json.dumps(manifest_record, separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
            descriptor = os.open(
                self._manifest_path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(descriptor, "ab") as stream:
                stream.write(encoded_record)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            image_path.unlink(missing_ok=True)
            raise DiagnosticCaptureError(
                f"cannot write diagnostic manifest {self._manifest_path}: {error}"
            ) from error

        self._frame_count = sequence
        return True

    def close(self) -> None:
        return None

    def _prepare_directory(self) -> None:
        if self._prepared:
            return
        try:
            self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self._directory, 0o700)
        except OSError as error:
            raise DiagnosticCaptureError(
                f"cannot prepare diagnostic directory {self._directory}: {error}"
            ) from error
        self._prepared = True

    @staticmethod
    def _add_result_text(image: Any, result: DetectionResult, cv2: Any) -> None:
        height, width = image.shape[:2]
        overlay_height = min(height, 58)
        cv2.rectangle(image, (0, 0), (width, overlay_height), (0, 0, 0), thickness=-1)
        status_text = f"{result.status.value}  {result.confidence:.2f}"
        reason_text = result.reason[:64]
        cv2.putText(
            image,
            status_text,
            (6, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            image,
            reason_text,
            (6, 43),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (180, 220, 255),
            1,
            cv2.LINE_AA,
        )
