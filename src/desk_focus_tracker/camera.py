from __future__ import annotations

import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Any


class CameraError(RuntimeError):
    """Raised when the camera cannot start or return a frame."""


class DependencyError(RuntimeError):
    """Raised when an optional runtime dependency is not installed."""


def import_cv2() -> ModuleType:
    try:
        import cv2
    except ImportError as error:
        raise DependencyError(
            "OpenCV is not installed. Install the project with: python -m pip install -e ."
        ) from error
    return cv2


@dataclass(frozen=True, slots=True)
class CameraProperties:
    width: int
    height: int
    fps: float
    zoom: float = 0.0
    zoom_supported: bool = False


@dataclass(frozen=True, slots=True)
class CameraDevice:
    index: int
    name: str
    path: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return {
            "index": self.index,
            "name": self.name,
            "path": self.path,
        }


def enumerate_camera_devices() -> tuple[CameraDevice, ...]:
    """List camera devices without capturing frames from them."""

    try:
        from cv2_enumerate_cameras import enumerate_cameras
    except ImportError as error:
        raise DependencyError(
            "Camera discovery is not installed. Install the project with: "
            f"python -m pip install -e . ({error})"
        ) from error

    cv2 = import_cv2()
    if sys.platform == "darwin":
        backend = cv2.CAP_AVFOUNDATION
    elif sys.platform.startswith("linux"):
        backend = cv2.CAP_V4L2
    else:
        backend = cv2.CAP_ANY

    devices = []
    seen_indices = set()
    for camera in enumerate_cameras(backend):
        index = int(camera.index)
        if index in seen_indices:
            continue
        seen_indices.add(index)
        name = str(camera.name).strip() or f"Camera {index}"
        path_value = str(camera.path).strip() if camera.path else None
        devices.append(CameraDevice(index=index, name=name, path=path_value))
    return tuple(devices)


class OpenCVCamera:
    """Capture one frame at a time without an application frame queue."""

    def __init__(
        self,
        camera_index: int,
        frame_width: int,
        frame_height: int,
        *,
        capture_fps: float | None = None,
        prefer_mjpeg: bool = False,
        zoom: float | None = None,
    ) -> None:
        if capture_fps is not None and capture_fps <= 0.0:
            raise ValueError("capture_fps must be positive")
        if zoom is not None and zoom < 0.0:
            raise ValueError("zoom must be zero or greater")
        self._camera_index = camera_index
        self._frame_width = frame_width
        self._frame_height = frame_height
        self._capture_fps = capture_fps
        self._prefer_mjpeg = prefer_mjpeg
        self._zoom = zoom
        self._zoom_supported = False
        self._cv2: ModuleType | None = None
        self._capture: Any = None

    def open(self) -> None:
        if self._capture is not None:
            return

        cv2 = import_cv2()
        capture = cv2.VideoCapture(self._camera_index)
        if not capture.isOpened():
            capture.release()
            raise CameraError(f"cannot open camera index {self._camera_index}")

        if self._prefer_mjpeg:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._frame_width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._frame_height)
        if self._capture_fps is not None:
            capture.set(cv2.CAP_PROP_FPS, self._capture_fps)
        if self._zoom is not None:
            self._zoom_supported = bool(capture.set(cv2.CAP_PROP_ZOOM, self._zoom))
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cv2 = cv2
        self._capture = capture

    def read(self) -> Any:
        if self._capture is None or self._cv2 is None:
            raise CameraError("camera is not open")

        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise CameraError("camera did not return a frame")

        height, width = frame.shape[:2]
        scale = min(self._frame_width / width, self._frame_height / height, 1.0)
        if scale < 1.0:
            target_size = (max(1, round(width * scale)), max(1, round(height * scale)))
            frame = self._cv2.resize(frame, target_size, interpolation=self._cv2.INTER_AREA)
        return frame

    def properties(self) -> CameraProperties:
        if self._capture is None or self._cv2 is None:
            raise CameraError("camera is not open")
        return CameraProperties(
            width=round(self._capture.get(self._cv2.CAP_PROP_FRAME_WIDTH)),
            height=round(self._capture.get(self._cv2.CAP_PROP_FRAME_HEIGHT)),
            fps=float(self._capture.get(self._cv2.CAP_PROP_FPS)),
            zoom=float(self._capture.get(self._cv2.CAP_PROP_ZOOM)),
            zoom_supported=self._zoom_supported,
        )

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = None
        self._cv2 = None
        self._zoom_supported = False

    def __enter__(self) -> OpenCVCamera:
        self.open()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
