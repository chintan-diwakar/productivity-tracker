from __future__ import annotations

import unittest

from know_your_focus.camera import CameraProperties
from know_your_focus.config import AppConfig
from know_your_focus.domain import DetectionResult, Status
from know_your_focus.preview import (
    InferenceWorker,
    PreviewPerformance,
    _destroy_window_safely,
    _window_is_visible,
    evidence_lines,
    pixel_box,
)
from know_your_focus.vision import NormalizedBox, Point, VisionEvidence


class EvidenceLinesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = AppConfig()

    def evidence(self, **overrides: object) -> VisionEvidence:
        values = {
            "person_count": 1,
            "person_confidence": 0.8,
            "phone_boxes": (),
            "phone_confidence": 0.0,
            "face_count": 1,
            "hand_points": (),
            "head_pitch_degrees": 0.0,
        }
        values.update(overrides)
        return VisionEvidence(**values)

    def test_reports_missing_phone_and_skipped_hand_model(self) -> None:
        result = DetectionResult(Status.FOCUSED_SCREEN, 0.65, "visible_face")

        lines = evidence_lines(self.evidence(), result, self.config)

        self.assertIn("PHONE: NOT DETECTED", lines)
        self.assertIn("HAND: NOT RUN (phone absent)", lines)
        self.assertIn("HEAD DOWN: NO (0.0 deg)", lines)

    def test_reports_phone_hand_and_downward_head(self) -> None:
        evidence = self.evidence(
            phone_boxes=(NormalizedBox(0.4, 0.5, 0.1, 0.2),),
            hand_points=(Point(0.45, 0.60),),
            head_pitch_degrees=18.0,
        )
        result = DetectionResult(Status.POSSIBLE_PHONE_USE, 0.8, "phone_use")

        lines = evidence_lines(evidence, result, self.config)

        self.assertIn("PHONE: DETECTED (1, score 0.00)", lines)
        self.assertIn("HAND: DETECTED (1 hand, 1 point)", lines)
        self.assertIn("HEAD DOWN: YES (18.0 deg)", lines)
        self.assertIn("PHONE THRESHOLD: 0.15", lines)
        self.assertIn("PERSON THRESHOLD: 0.35", lines)


class PixelBoxTest(unittest.TestCase):
    def test_converts_and_clamps_normalized_box(self) -> None:
        box = NormalizedBox(-0.1, 0.25, 1.2, 0.5)

        result = pixel_box(box, width=320, height=240)

        self.assertEqual(result, (0, 60, 320, 180))


class ClosedWindowCV2:
    class error(Exception):
        pass

    WND_PROP_VISIBLE = 1

    def getWindowProperty(self, window_name: str, property_id: int) -> float:
        raise self.error("NULL guiReceiver")

    def destroyWindow(self, window_name: str) -> None:
        raise self.error("NULL guiReceiver")


class WindowCleanupTest(unittest.TestCase):
    def test_closed_window_is_not_visible_when_opencv_raises(self) -> None:
        self.assertFalse(_window_is_visible(ClosedWindowCV2(), "preview"))

    def test_destroying_an_already_closed_window_does_not_raise(self) -> None:
        _destroy_window_safely(ClosedWindowCV2(), "preview")


class FakeDetector:
    def analyze(self, frame: object) -> VisionEvidence:
        return VisionEvidence(
            person_count=int(frame),
            person_confidence=0.8,
            phone_boxes=(),
            phone_confidence=0.0,
            face_count=1,
            hand_points=(),
            head_pitch_degrees=0.0,
        )

    def classify(self, evidence: VisionEvidence) -> DetectionResult:
        return DetectionResult(Status.FOCUSED_SCREEN, 0.65, "fake_result")


class InferenceWorkerTest(unittest.TestCase):
    def test_processes_only_the_latest_pending_frame(self) -> None:
        worker = InferenceWorker(FakeDetector())
        worker.submit(1)
        worker.submit(2)
        worker.start()
        try:
            snapshot = worker.wait_for_snapshot(timeout=1.0)
        finally:
            worker.stop()

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.evidence.person_count, 2)
        self.assertEqual(snapshot.sequence, 1)

    def test_adds_camera_and_rate_metrics(self) -> None:
        evidence = FakeDetector().analyze(1)
        result = FakeDetector().classify(evidence)
        performance = PreviewPerformance(
            camera=CameraProperties(1280, 720, 60.0, zoom=0.0, zoom_supported=True),
            target_display_fps=60.0,
            measured_display_fps=58.5,
            target_inference_fps=10.0,
            inference_latency_ms=46.2,
        )

        lines = evidence_lines(evidence, result, AppConfig(), performance)

        self.assertIn("CAMERA: 1280x720 (driver 60.0 FPS)", lines)
        self.assertIn("ZOOM: 0 (widest)", lines)
        self.assertIn("DISPLAY: 58.5 / 60.0 FPS", lines)
        self.assertIn("INFERENCE: 46.2 ms / 10.0 FPS target", lines)


if __name__ == "__main__":
    unittest.main()
