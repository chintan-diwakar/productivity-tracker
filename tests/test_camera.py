from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from know_your_focus.camera import OpenCVCamera, enumerate_camera_devices


class OpenCVCameraTest(unittest.TestCase):
    def test_rejects_nonpositive_capture_rate(self) -> None:
        with self.assertRaisesRegex(ValueError, "capture_fps"):
            OpenCVCamera(0, 1280, 720, capture_fps=0.0)

    def test_rejects_negative_zoom(self) -> None:
        with self.assertRaisesRegex(ValueError, "zoom"):
            OpenCVCamera(0, 1280, 720, zoom=-1.0)


class CameraDiscoveryTest(unittest.TestCase):
    def test_lists_named_linux_cameras_without_duplicate_indices(self) -> None:
        fake_cv2 = SimpleNamespace(CAP_ANY=0, CAP_V4L2=200, CAP_AVFOUNDATION=1200)
        camera_module = SimpleNamespace(
            enumerate_cameras=lambda backend: [
                SimpleNamespace(index=0, name="Built-in Camera", path="/dev/video0"),
                SimpleNamespace(index=0, name="Built-in Camera", path="/dev/video0"),
                SimpleNamespace(index=2, name="USB Camera", path="/dev/video2"),
            ]
        )

        with (
            patch("know_your_focus.camera.import_cv2", return_value=fake_cv2),
            patch("know_your_focus.camera.sys.platform", "linux"),
            patch.dict("sys.modules", {"cv2_enumerate_cameras": camera_module}),
        ):
            cameras = enumerate_camera_devices()

        self.assertEqual([camera.index for camera in cameras], [0, 2])
        self.assertEqual([camera.name for camera in cameras], ["Built-in Camera", "USB Camera"])


if __name__ == "__main__":
    unittest.main()
