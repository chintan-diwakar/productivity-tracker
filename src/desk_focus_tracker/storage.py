from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from desk_focus_tracker.domain import (
    DetectionResult,
    StatisticsCategory,
    Status,
    statistics_category,
)


class StorageError(RuntimeError):
    """Raised when a status event cannot be stored."""


class JsonlSessionLogger:
    """Store session events and rebuild daily summaries from valid records."""

    schema_version = 1

    def __init__(
        self,
        data_dir: Path,
        model_version: str,
        configuration_version: int,
    ) -> None:
        self._data_dir = data_dir
        self._model_version = model_version
        self._configuration_version = configuration_version
        self._current: DetectionResult | None = None
        self._started_at: datetime | None = None
        self._started_monotonic: float | None = None
        self._closed = False
        self._prepare_directory()

    def _prepare_directory(self) -> None:
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self._data_dir, 0o700)
        except OSError as error:
            raise StorageError(
                f"cannot prepare data directory {self._data_dir}: {error}"
            ) from error

    def start(self, initial: DetectionResult, now: datetime, monotonic_seconds: float) -> None:
        if self._current is not None:
            raise StorageError("session logger already started")
        if now.tzinfo is None:
            raise StorageError("event timestamps must include a UTC offset")

        self._append_event(
            now,
            {
                "event_type": "session_start",
                "status": initial.status.value,
                "confidence": initial.confidence,
                "reason": initial.reason,
            },
        )
        self._current = initial
        self._started_at = now
        self._started_monotonic = monotonic_seconds

    def transition(self, result: DetectionResult, now: datetime, monotonic_seconds: float) -> None:
        current, _, started_monotonic = self._require_active()
        if result.status is current.status:
            return

        elapsed = max(0.0, monotonic_seconds - started_monotonic)
        self._append_event(
            now,
            {
                "event_type": "status_transition",
                "status": result.status.value,
                "confidence": result.confidence,
                "reason": result.reason,
                "previous_status": current.status.value,
                "elapsed_previous_seconds": elapsed,
            },
        )
        self._current = result
        self._started_at = now
        self._started_monotonic = monotonic_seconds
        self.rebuild_summary(now.date(), generated_at=now)

    def close(self, now: datetime, monotonic_seconds: float) -> None:
        if self._closed:
            return
        if self._current is None:
            self._closed = True
            return

        current, _, started_monotonic = self._require_active()
        elapsed = max(0.0, monotonic_seconds - started_monotonic)
        self._append_event(
            now,
            {
                "event_type": "session_end",
                "status": current.status.value,
                "confidence": current.confidence,
                "reason": current.reason,
                "previous_status": current.status.value,
                "elapsed_previous_seconds": elapsed,
            },
        )
        self.rebuild_summary(now.date(), generated_at=now)
        self._closed = True

    def _require_active(self) -> tuple[DetectionResult, datetime, float]:
        if self._closed:
            raise StorageError("session logger is closed")
        if self._current is None or self._started_at is None or self._started_monotonic is None:
            raise StorageError("session logger is not started")
        return self._current, self._started_at, self._started_monotonic

    def _append_event(self, now: datetime, payload: dict[str, Any]) -> None:
        if now.tzinfo is None:
            raise StorageError("event timestamps must include a UTC offset")

        event = {
            "schema_version": self.schema_version,
            "timestamp": now.isoformat(),
            "model_version": self._model_version,
            "configuration_version": self._configuration_version,
            **payload,
        }
        path = self._event_path(now.date())
        encoded = (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        try:
            descriptor = os.open(path, flags, 0o600)
            with os.fdopen(descriptor, "ab") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise StorageError(f"cannot write event log {path}: {error}") from error

    def rebuild_summary(self, day: date, generated_at: datetime | None = None) -> dict[str, Any]:
        seconds_by_status = {status.value: 0.0 for status in Status}
        event_path = self._event_path(day)
        if event_path.exists():
            try:
                with event_path.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            event = json.loads(line)
                            previous_status = Status(event["previous_status"])
                            elapsed = float(event["elapsed_previous_seconds"])
                        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                            continue
                        if elapsed >= 0.0:
                            seconds_by_status[previous_status.value] += elapsed
            except OSError as error:
                raise StorageError(f"cannot read event log {event_path}: {error}") from error

        category_seconds = {category.value: 0.0 for category in StatisticsCategory}
        for status in Status:
            category = statistics_category(status)
            category_seconds[category.value] += seconds_by_status[status.value]

        classified = (
            category_seconds[StatisticsCategory.PRODUCTIVE.value]
            + category_seconds[StatisticsCategory.UNPRODUCTIVE.value]
        )
        productive_ratio = (
            category_seconds[StatisticsCategory.PRODUCTIVE.value] / classified
            if classified > 0.0
            else None
        )
        summary = {
            "schema_version": self.schema_version,
            "date": day.isoformat(),
            "generated_at": (generated_at or datetime.now().astimezone()).isoformat(),
            "status_seconds": seconds_by_status,
            "category_seconds": category_seconds,
            "productive_ratio": productive_ratio,
        }
        self._write_summary_atomic(day, summary)
        return summary

    def _write_summary_atomic(self, day: date, summary: dict[str, Any]) -> None:
        destination = self._summary_path(day)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._data_dir,
                prefix=f".{destination.name}.",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                json.dump(summary, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, destination)
        except OSError as error:
            raise StorageError(f"cannot write daily summary {destination}: {error}") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _event_path(self, day: date) -> Path:
        return self._data_dir / f"events-{day.isoformat()}.jsonl"

    def _summary_path(self, day: date) -> Path:
        return self._data_dir / f"summary-{day.isoformat()}.json"
