from __future__ import annotations

import unittest

from desk_focus_tracker.camera import OpenCVCamera


class OpenCVCameraTest(unittest.TestCase):
    def test_rejects_nonpositive_capture_rate(self) -> None:
        with self.assertRaisesRegex(ValueError, "capture_fps"):
            OpenCVCamera(0, 1280, 720, capture_fps=0.0)

    def test_rejects_negative_zoom(self) -> None:
        with self.assertRaisesRegex(ValueError, "zoom"):
            OpenCVCamera(0, 1280, 720, zoom=-1.0)


if __name__ == "__main__":
    unittest.main()
