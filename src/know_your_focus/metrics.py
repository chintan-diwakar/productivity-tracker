from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

from know_your_focus.domain import (
    DetectionResult,
    StatisticsCategory,
    Status,
    statistics_category,
)


@dataclass(frozen=True, slots=True)
class DailyMetrics:
    day: date
    status_seconds: dict[str, float]
    category_seconds: dict[str, float]
    focused_active_ratio: float | None
    classified_coverage: float | None
    classified_seconds: float
    observed_seconds: float
    tracked_seconds: float

    def to_mapping(self) -> dict[str, object]:
        return {
            "date": self.day.isoformat(),
            "status_seconds": self.status_seconds,
            "category_seconds": self.category_seconds,
            "focused_active_ratio": self.focused_active_ratio,
            # Keep the first prototype field for readers of existing summary files.
            "productive_ratio": self.focused_active_ratio,
            "classified_coverage": self.classified_coverage,
            "classified_seconds": self.classified_seconds,
            "observed_seconds": self.observed_seconds,
            "tracked_seconds": self.tracked_seconds,
        }


@dataclass(frozen=True, slots=True)
class SessionMetrics:
    session_id: str
    started_at: datetime
    ended_at: datetime | None
    active: bool
    final_status: Status
    final_confidence: float
    final_reason: str
    transition_count: int
    diagnostic_output_enabled: bool
    diagnostic_frame_count: int
    status_seconds: dict[str, float]
    category_seconds: dict[str, float]
    focused_active_ratio: float | None
    classified_coverage: float | None
    classified_seconds: float
    observed_seconds: float
    tracked_seconds: float

    def to_mapping(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at is not None else None,
            "state": "active" if self.active else "complete",
            "final_status": self.final_status.value,
            "final_confidence": self.final_confidence,
            "final_reason": self.final_reason,
            "transition_count": self.transition_count,
            "diagnostic_output_enabled": self.diagnostic_output_enabled,
            "diagnostic_frame_count": self.diagnostic_frame_count,
            "status_seconds": self.status_seconds,
            "category_seconds": self.category_seconds,
            "focused_active_ratio": self.focused_active_ratio,
            "classified_coverage": self.classified_coverage,
            "classified_seconds": self.classified_seconds,
            "observed_seconds": self.observed_seconds,
            "tracked_seconds": self.tracked_seconds,
        }


def calculate_daily_metrics(day: date, values: Mapping[str, float]) -> DailyMetrics:
    status_seconds = {
        status.value: max(0.0, float(values.get(status.value, 0.0))) for status in Status
    }
    category_seconds = {category.value: 0.0 for category in StatisticsCategory}
    for status in Status:
        category = statistics_category(status)
        category_seconds[category.value] += status_seconds[status.value]

    focused = category_seconds[StatisticsCategory.PRODUCTIVE.value]
    phone = category_seconds[StatisticsCategory.UNPRODUCTIVE.value]
    uncertain = category_seconds[StatisticsCategory.UNCERTAIN.value]
    classified = focused + phone
    observed = classified + uncertain
    tracked = sum(category_seconds.values())

    return DailyMetrics(
        day=day,
        status_seconds=status_seconds,
        category_seconds=category_seconds,
        focused_active_ratio=focused / classified if classified > 0.0 else None,
        classified_coverage=classified / observed if observed > 0.0 else None,
        classified_seconds=classified,
        observed_seconds=observed,
        tracked_seconds=tracked,
    )


def calculate_session_metrics(
    session_id: str,
    started_at: datetime,
    ended_at: datetime | None,
    active: bool,
    final_result: DetectionResult,
    transition_count: int,
    diagnostic_output_enabled: bool,
    diagnostic_frame_count: int,
    values: Mapping[str, float],
) -> SessionMetrics:
    daily = calculate_daily_metrics(started_at.date(), values)
    return SessionMetrics(
        session_id=session_id,
        started_at=started_at,
        ended_at=ended_at,
        active=active,
        final_status=final_result.status,
        final_confidence=final_result.confidence,
        final_reason=final_result.reason,
        transition_count=transition_count,
        diagnostic_output_enabled=diagnostic_output_enabled,
        diagnostic_frame_count=diagnostic_frame_count,
        status_seconds=daily.status_seconds,
        category_seconds=daily.category_seconds,
        focused_active_ratio=daily.focused_active_ratio,
        classified_coverage=daily.classified_coverage,
        classified_seconds=daily.classified_seconds,
        observed_seconds=daily.observed_seconds,
        tracked_seconds=daily.tracked_seconds,
    )


def format_duration(seconds: float) -> str:
    total_seconds = max(0, round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}h {minutes:02d}m"
    if minutes:
        return f"{minutes:d}m {remaining_seconds:02d}s"
    return f"{remaining_seconds:d}s"


def format_ratio(value: float | None) -> str:
    return "Not enough data" if value is None else f"{value:.0%}"
