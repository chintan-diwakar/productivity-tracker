from __future__ import annotations

import unittest

from desk_focus_tracker.config import AppConfig
from desk_focus_tracker.domain import DetectionResult, Status
from desk_focus_tracker.preview import evidence_lines, pixel_box
from desk_focus_tracker.vision import NormalizedBox, Point, VisionEvidence


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
        self.assertIn("HAND: DETECTED (1 points)", lines)
        self.assertIn("HEAD DOWN: YES (18.0 deg)", lines)


class PixelBoxTest(unittest.TestCase):
    def test_converts_and_clamps_normalized_box(self) -> None:
        box = NormalizedBox(-0.1, 0.25, 1.2, 0.5)

        result = pixel_box(box, width=320, height=240)

        self.assertEqual(result, (0, 60, 320, 180))


if __name__ == "__main__":
    unittest.main()
