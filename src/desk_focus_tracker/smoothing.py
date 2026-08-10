from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass

from desk_focus_tracker.domain import DetectionResult, Status


@dataclass(frozen=True, slots=True)
class SmoothingUpdate:
    stable: DetectionResult
    changed: bool


class TemporalSmoother:
    """Convert frame results into stable status transitions."""

    def __init__(self, window_samples: int, minimum_matching_samples: int) -> None:
        if window_samples <= 0:
            raise ValueError("window_samples must be positive")
        if not 0 < minimum_matching_samples <= window_samples:
            raise ValueError("minimum_matching_samples must not exceed window_samples")

        self._window: deque[DetectionResult] = deque(maxlen=window_samples)
        self._minimum_matching_samples = minimum_matching_samples
        self._stable = DetectionResult(Status.UNCERTAIN, 0.0, "tracker_starting")

    @property
    def stable(self) -> DetectionResult:
        return self._stable

    def update(self, candidate: DetectionResult) -> SmoothingUpdate:
        self._window.append(candidate)
        if candidate.status is self._stable.status:
            return SmoothingUpdate(self._stable, False)

        counts = Counter(item.status for item in self._window)
        if counts[candidate.status] < self._minimum_matching_samples:
            return SmoothingUpdate(self._stable, False)

        matching = [item for item in self._window if item.status is candidate.status]
        confidence = sum(item.confidence for item in matching) / len(matching)
        self._stable = DetectionResult(
            candidate.status,
            confidence,
            candidate.reason,
            candidate.metrics,
        )
        self._window.clear()
        self._window.append(candidate)
        return SmoothingUpdate(self._stable, True)
