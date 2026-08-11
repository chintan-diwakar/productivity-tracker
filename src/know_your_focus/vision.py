from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from know_your_focus.domain import DetectionResult, Status


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
    person_boxes: tuple[NormalizedBox, ...] = ()
    face_boxes: tuple[NormalizedBox, ...] = ()
    person_scores: tuple[float, ...] = ()
    phone_scores: tuple[float, ...] = ()


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
        downward_pose_grace_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if downward_pose_grace_seconds < 0.0:
            raise ValueError("downward_pose_grace_seconds must be zero or greater")
        self._downward_pitch_threshold_degrees = downward_pitch_threshold_degrees
        self._neutral_head_pitch_degrees = neutral_head_pitch_degrees
        self._head_pitch_sign = head_pitch_sign
        self._phone_hand_max_distance = phone_hand_max_distance
        self._downward_pose_grace_seconds = downward_pose_grace_seconds
        self._clock = clock
        self._downward_pose_valid_until = 0.0

    def classify(self, evidence: VisionEvidence) -> DetectionResult:
        now = self._clock()
        if evidence.person_count == 0 and evidence.face_count == 0:
            return self._result(Status.AWAY, 0.70, "no_person_or_face_detected", evidence)

        if evidence.person_count > 1 or evidence.face_count > 1:
            return self._result(Status.UNCERTAIN, 0.20, "multiple_people_detected", evidence)

        phone_hand_distance = minimum_phone_hand_distance(evidence)
        phone_is_near_hand = (
            phone_hand_distance is not None and phone_hand_distance <= self._phone_hand_max_distance
        )

        if evidence.face_count == 0:
            if evidence.phone_boxes and phone_is_near_hand:
                recent_downward_pose = now <= self._downward_pose_valid_until
                confidence_scale = 0.90 if recent_downward_pose else 0.75
                confidence = max(0.20, evidence.phone_confidence * confidence_scale)
                return self._result(
                    Status.POSSIBLE_PHONE_USE,
                    confidence,
                    (
                        "phone_near_hand_and_recent_downward_head_pose"
                        if recent_downward_pose
                        else "phone_near_hand_with_face_occluded"
                    ),
                    evidence,
                )
            confidence = max(0.20, evidence.person_confidence)
            return self._result(
                Status.LOOKING_AWAY,
                confidence,
                "person_without_visible_face",
                evidence,
            )

        if evidence.head_pitch_degrees is None:
            if evidence.phone_boxes and phone_is_near_hand:
                confidence = max(0.20, evidence.phone_confidence * 0.75)
                return self._result(
                    Status.POSSIBLE_PHONE_USE,
                    confidence,
                    "phone_near_hand_without_head_pose",
                    evidence,
                )
            return self._result(Status.UNCERTAIN, 0.20, "head_pose_unavailable", evidence)

        relative_pitch = self._head_pitch_sign * (
            evidence.head_pitch_degrees - self._neutral_head_pitch_degrees
        )
        head_is_down = relative_pitch >= self._downward_pitch_threshold_degrees
        if head_is_down:
            self._downward_pose_valid_until = now + self._downward_pose_grace_seconds
        else:
            self._downward_pose_valid_until = 0.0

        if evidence.phone_boxes and phone_is_near_hand:
            confidence_scale = 1.0 if head_is_down else 0.75
            confidence = max(0.20, evidence.phone_confidence * confidence_scale)
            return self._result(
                Status.POSSIBLE_PHONE_USE,
                confidence,
                (
                    "phone_near_hand_and_downward_head_pose"
                    if head_is_down
                    else "phone_near_hand_without_downward_head_pose"
                ),
                evidence,
            )

        if head_is_down:
            return self._result(
                Status.LOOKING_DOWN,
                0.70,
                "downward_head_pose_without_hand_phone",
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
            ("person_confidence", evidence.person_confidence),
            ("face_count", float(evidence.face_count)),
            ("phone_count", float(len(evidence.phone_boxes))),
            ("phone_confidence", evidence.phone_confidence),
            ("hand_count", float(math.ceil(len(evidence.hand_points) / 21))),
            ("hand_point_count", float(len(evidence.hand_points))),
        ]
        if evidence.person_scores:
            metrics.append(("person_min_confidence", min(evidence.person_scores)))
        if evidence.phone_scores:
            metrics.append(("phone_min_confidence", min(evidence.phone_scores)))
        if evidence.head_pitch_degrees is not None:
            metrics.append(("head_pitch_degrees", evidence.head_pitch_degrees))
        distance = minimum_phone_hand_distance(evidence)
        if distance is not None:
            metrics.append(("phone_hand_distance", distance))
        return DetectionResult(status, confidence, reason, tuple(metrics))
