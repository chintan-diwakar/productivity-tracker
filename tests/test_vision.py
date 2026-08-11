from __future__ import annotations

import math
import unittest

from know_your_focus.domain import Status
from know_your_focus.vision import (
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

    def test_one_hand_phone_use_does_not_require_downward_head_pose(self) -> None:
        one_hand = tuple(Point(0.46, 0.60) for _point in range(21))
        evidence = self.evidence(
            phone_boxes=(NormalizedBox(0.4, 0.5, 0.1, 0.2),),
            phone_confidence=0.8,
            hand_points=one_hand,
            head_pitch_degrees=5.0,
        )

        result = self.classifier.classify(evidence)

        self.assertIs(result.status, Status.POSSIBLE_PHONE_USE)
        self.assertEqual(result.reason, "phone_near_hand_without_downward_head_pose")
        self.assertEqual(dict(result.metrics)["hand_count"], 1.0)

    def test_phone_far_from_hand_does_not_count_as_phone_use(self) -> None:
        evidence = self.evidence(
            phone_boxes=(NormalizedBox(0.8, 0.8, 0.1, 0.1),),
            phone_confidence=0.8,
            hand_points=(Point(0.1, 0.1),),
            head_pitch_degrees=5.0,
        )

        result = self.classifier.classify(evidence)

        self.assertIs(result.status, Status.FOCUSED_SCREEN)

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

    def test_keeps_phone_use_during_brief_face_occlusion_after_downward_pose(self) -> None:
        now = [10.0]
        classifier = BehaviorClassifier(
            downward_pitch_threshold_degrees=15.0,
            neutral_head_pitch_degrees=0.0,
            head_pitch_sign=1.0,
            phone_hand_max_distance=0.2,
            clock=lambda: now[0],
        )
        classifier.classify(self.evidence(head_pitch_degrees=20.0))
        now[0] = 13.0

        result = classifier.classify(
            self.evidence(
                phone_boxes=(NormalizedBox(0.4, 0.5, 0.1, 0.2),),
                phone_confidence=0.9,
                hand_points=(Point(0.46, 0.60),),
                face_count=0,
                head_pitch_degrees=None,
            )
        )

        self.assertIs(result.status, Status.POSSIBLE_PHONE_USE)
        self.assertEqual(result.reason, "phone_near_hand_and_recent_downward_head_pose")

    def test_face_occlusion_still_counts_a_phone_near_one_hand(self) -> None:
        now = [10.0]
        classifier = BehaviorClassifier(
            downward_pitch_threshold_degrees=15.0,
            neutral_head_pitch_degrees=0.0,
            head_pitch_sign=1.0,
            phone_hand_max_distance=0.2,
            clock=lambda: now[0],
        )
        classifier.classify(self.evidence(head_pitch_degrees=20.0))
        now[0] = 16.0

        result = classifier.classify(
            self.evidence(
                phone_boxes=(NormalizedBox(0.4, 0.5, 0.1, 0.2),),
                phone_confidence=0.9,
                hand_points=(Point(0.46, 0.60),),
                face_count=0,
                head_pitch_degrees=None,
            )
        )

        self.assertIs(result.status, Status.POSSIBLE_PHONE_USE)
        self.assertEqual(result.reason, "phone_near_hand_with_face_occluded")

    def test_upright_pose_uses_the_lower_confidence_phone_rule(self) -> None:
        now = [10.0]
        classifier = BehaviorClassifier(
            downward_pitch_threshold_degrees=15.0,
            neutral_head_pitch_degrees=0.0,
            head_pitch_sign=1.0,
            phone_hand_max_distance=0.2,
            clock=lambda: now[0],
        )
        classifier.classify(self.evidence(head_pitch_degrees=20.0))
        now[0] = 11.0
        classifier.classify(self.evidence(head_pitch_degrees=5.0))
        now[0] = 12.0

        result = classifier.classify(
            self.evidence(
                phone_boxes=(NormalizedBox(0.4, 0.5, 0.1, 0.2),),
                phone_confidence=0.9,
                hand_points=(Point(0.46, 0.60),),
                face_count=0,
                head_pitch_degrees=None,
            )
        )

        self.assertIs(result.status, Status.POSSIBLE_PHONE_USE)
        self.assertEqual(result.reason, "phone_near_hand_with_face_occluded")
        self.assertAlmostEqual(result.confidence, 0.675)


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
