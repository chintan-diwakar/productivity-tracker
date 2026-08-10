from __future__ import annotations

import math
import unittest

from desk_focus_tracker.domain import Status
from desk_focus_tracker.vision import (
    BehaviorClassifier,
    NormalizedBox,
    Point,
    VisionEvidence,
    pitch_degrees_from_transformation_matrix,
)


class BehaviorClassifierTest(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = BehaviorClassifier(
            downward_pitch_threshold_degrees=15.0,
            neutral_head_pitch_degrees=0.0,
            head_pitch_sign=1.0,
            phone_hand_max_distance=0.2,
        )

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

    def test_classifies_phone_use_from_combined_evidence(self) -> None:
        evidence = self.evidence(
            phone_boxes=(NormalizedBox(0.4, 0.5, 0.1, 0.2),),
            phone_confidence=0.9,
            hand_points=(Point(0.46, 0.60),),
            head_pitch_degrees=20.0,
        )

        result = self.classifier.classify(evidence)

        self.assertIs(result.status, Status.POSSIBLE_PHONE_USE)

    def test_does_not_call_downward_look_phone_use_without_hand(self) -> None:
        evidence = self.evidence(
            phone_boxes=(NormalizedBox(0.4, 0.5, 0.1, 0.2),),
            phone_confidence=0.9,
            head_pitch_degrees=20.0,
        )

        result = self.classifier.classify(evidence)

        self.assertIs(result.status, Status.LOOKING_DOWN)

    def test_classifies_visible_aligned_face_as_focused(self) -> None:
        result = self.classifier.classify(self.evidence())

        self.assertIs(result.status, Status.FOCUSED_SCREEN)

    def test_classifies_multiple_people_as_uncertain(self) -> None:
        result = self.classifier.classify(self.evidence(person_count=2))

        self.assertIs(result.status, Status.UNCERTAIN)

    def test_classifies_no_presence_as_away(self) -> None:
        result = self.classifier.classify(
            self.evidence(person_count=0, face_count=0, head_pitch_degrees=None)
        )

        self.assertIs(result.status, Status.AWAY)


class HeadPitchTest(unittest.TestCase):
    def test_extracts_pitch_from_rotation_matrix(self) -> None:
        angle = math.radians(20.0)
        matrix = (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, math.cos(angle), -math.sin(angle), 0.0),
            (0.0, math.sin(angle), math.cos(angle), 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )

        result = pitch_degrees_from_transformation_matrix(matrix)

        self.assertAlmostEqual(result, 20.0)


if __name__ == "__main__":
    unittest.main()
