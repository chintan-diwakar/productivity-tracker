from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    FOCUSED_SCREEN = "FOCUSED_SCREEN"
    POSSIBLE_PHONE_USE = "POSSIBLE_PHONE_USE"
    LOOKING_DOWN = "LOOKING_DOWN"
    LOOKING_AWAY = "LOOKING_AWAY"
    AWAY = "AWAY"
    SYSTEM_IDLE = "SYSTEM_IDLE"
    UNCERTAIN = "UNCERTAIN"
    PAUSED = "PAUSED"
    CAMERA_ERROR = "CAMERA_ERROR"


class StatisticsCategory(str, Enum):
    PRODUCTIVE = "productive"
    UNPRODUCTIVE = "unproductive"
    UNCERTAIN = "uncertain"
    EXCLUDED = "excluded"


UNCERTAIN_STATUSES = {
    Status.LOOKING_DOWN,
    Status.LOOKING_AWAY,
    Status.UNCERTAIN,
}

EXCLUDED_STATUSES = {
    Status.AWAY,
    Status.SYSTEM_IDLE,
    Status.PAUSED,
    Status.CAMERA_ERROR,
}


def statistics_category(status: Status) -> StatisticsCategory:
    if status is Status.FOCUSED_SCREEN:
        return StatisticsCategory.PRODUCTIVE
    if status is Status.POSSIBLE_PHONE_USE:
        return StatisticsCategory.UNPRODUCTIVE
    if status in UNCERTAIN_STATUSES:
        return StatisticsCategory.UNCERTAIN
    return StatisticsCategory.EXCLUDED


@dataclass(frozen=True, slots=True)
class DetectionResult:
    status: Status
    confidence: float
    reason: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if not self.reason:
            raise ValueError("reason must not be empty")
