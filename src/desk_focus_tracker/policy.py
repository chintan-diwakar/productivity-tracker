from __future__ import annotations

from desk_focus_tracker.domain import DetectionResult, Status


class AwayPolicy:
    """Require continuous no-face evidence before an AWAY result."""

    def __init__(self, timeout_seconds: float) -> None:
        if timeout_seconds < 0.0:
            raise ValueError("timeout_seconds must be zero or greater")
        self._timeout_seconds = timeout_seconds
        self._no_person_since: float | None = None

    def apply(self, result: DetectionResult, monotonic_seconds: float) -> DetectionResult:
        if result.status is not Status.AWAY:
            self._no_person_since = None
            return result

        if self._no_person_since is None:
            self._no_person_since = monotonic_seconds

        elapsed = max(0.0, monotonic_seconds - self._no_person_since)
        if elapsed < self._timeout_seconds:
            return DetectionResult(
                Status.UNCERTAIN,
                result.confidence,
                "waiting_for_away_timeout",
            )
        return result
