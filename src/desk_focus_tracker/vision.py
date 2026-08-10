from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from desk_focus_tracker.domain import DetectionResult, Status


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class NormalizedBox:
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2.0, self.y + self.height / 2.0)


@dataclass(frozen=True, slots=True)
class VisionEvidence:
    person_count: int
    person_confidence: float
    phone_boxes: tuple[NormalizedBox, ...]
    phone_confidence: float
    face_count: int
    hand_points: tuple[Point, ...]
    head_pitch_degrees: float | None


def minimum_phone_hand_distance(evidence: VisionEvidence) -> float | None:
    if not evidence.phone_boxes or not evidence.hand_points:
        return None
    return min(
        math.hypot(phone.center.x - hand.x, phone.center.y - hand.y)
        for phone in evidence.phone_boxes
        for hand in evidence.hand_points
    )


def pitch_degrees_from_transformation_matrix(matrix: Sequence[Sequence[float]]) -> float:
    if len(matrix) < 3 or any(len(row) < 3 for row in matrix[:3]):
        raise ValueError("facial transformation matrix must contain a 3x3 rotation matrix")
    return math.degrees(math.atan2(float(matrix[2][1]), float(matrix[2][2])))


class BehaviorClassifier:
    def __init__(
        self,
        downward_pitch_threshold_degrees: float,
        neutral_head_pitch_degrees: float,
        head_pitch_sign: float,
        phone_hand_max_distance: float,
    ) -> None:
        self._downward_pitch_threshold_degrees = downward_pitch_threshold_degrees
        self._neutral_head_pitch_degrees = neutral_head_pitch_degrees
        self._head_pitch_sign = head_pitch_sign
        self._phone_hand_max_distance = phone_hand_max_distance

    def classify(self, evidence: VisionEvidence) -> DetectionResult:
        if evidence.person_count == 0 and evidence.face_count == 0:
            return self._result(Status.AWAY, 0.70, "no_person_or_face_detected", evidence)

        if evidence.person_count > 1 or evidence.face_count > 1:
            return self._result(Status.UNCERTAIN, 0.20, "multiple_people_detected", evidence)

        if evidence.face_count == 0:
            confidence = max(0.20, evidence.person_confidence)
            return self._result(
                Status.LOOKING_AWAY,
                confidence,
                "person_without_visible_face",
                evidence,
            )

        if evidence.head_pitch_degrees is None:
            return self._result(Status.UNCERTAIN, 0.20, "head_pose_unavailable", evidence)

        relative_pitch = self._head_pitch_sign * (
            evidence.head_pitch_degrees - self._neutral_head_pitch_degrees
        )
        head_is_down = relative_pitch >= self._downward_pitch_threshold_degrees
        phone_hand_distance = minimum_phone_hand_distance(evidence)
        phone_is_near_hand = (
            phone_hand_distance is not None and phone_hand_distance <= self._phone_hand_max_distance
        )

        if evidence.phone_boxes and phone_is_near_hand and head_is_down:
            confidence = max(0.20, evidence.phone_confidence)
            return self._result(
                Status.POSSIBLE_PHONE_USE,
                confidence,
                "phone_near_hand_and_downward_head_pose",
                evidence,
            )

        if head_is_down:
            return self._result(
                Status.LOOKING_DOWN,
                0.70,
                "downward_head_pose_without_hand_phone",
                evidence,
            )

        if evidence.phone_boxes and phone_is_near_hand:
            confidence = max(0.20, evidence.phone_confidence)
            return self._result(
                Status.UNCERTAIN,
                confidence,
                "phone_near_hand_without_downward_head_pose",
                evidence,
            )

        return self._result(
            Status.FOCUSED_SCREEN,
            0.65,
            "visible_face_without_phone_use",
            evidence,
        )

    @staticmethod
    def _result(
        status: Status,
        confidence: float,
        reason: str,
        evidence: VisionEvidence,
    ) -> DetectionResult:
        metrics = [
            ("person_count", float(evidence.person_count)),
            ("face_count", float(evidence.face_count)),
            ("phone_count", float(len(evidence.phone_boxes))),
            ("hand_point_count", float(len(evidence.hand_points))),
        ]
        if evidence.head_pitch_degrees is not None:
            metrics.append(("head_pitch_degrees", evidence.head_pitch_degrees))
        distance = minimum_phone_hand_distance(evidence)
        if distance is not None:
            metrics.append(("phone_hand_distance", distance))
        return DetectionResult(status, confidence, reason, tuple(metrics))
