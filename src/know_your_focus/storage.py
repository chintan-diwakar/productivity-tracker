from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from contextlib import suppress
from datetime import date, datetime, time, timedelta
from pathlib import Path
from threading import RLock
from typing import Any

from know_your_focus.domain import DetectionResult, Status
from know_your_focus.metrics import (
    DailyMetrics,
    SessionMetrics,
    calculate_daily_metrics,
    calculate_session_metrics,
)


class StorageError(RuntimeError):
    """Raised when a status event cannot be stored."""


class JsonlSessionLogger:
    """Store session events and rebuild daily summaries from valid records."""

    schema_version = 2

    def __init__(
        self,
        data_dir: Path,
        model_version: str,
        configuration_version: int,
        session_id: str | None = None,
        diagnostic_output_enabled: bool = False,
    ) -> None:
        self._data_dir = data_dir
        self._model_version = model_version
        self._configuration_version = configuration_version
        self._session_id = session_id or uuid.uuid4().hex
        self._session_directory = self._data_dir / "sessions" / self._session_id
        self._session_started_at: datetime | None = None
        self._session_ended_at: datetime | None = None
        self._session_status_seconds = {status.value: 0.0 for status in Status}
        self._session_transition_count = 0
        self._diagnostic_output_enabled = diagnostic_output_enabled
        self._diagnostic_frame_count = 0
        self._current: DetectionResult | None = None
        self._started_at: datetime | None = None
        self._started_monotonic: float | None = None
        self._closed = False
        self._lock = RLock()
        self._prepare_directory()

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def session_directory(self) -> Path:
        return self._session_directory

    @property
    def session_started(self) -> bool:
        with self._lock:
            return self._session_started_at is not None

    def _prepare_directory(self) -> None:
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self._data_dir, 0o700)
        except OSError as error:
            raise StorageError(
                f"cannot prepare data directory {self._data_dir}: {error}"
            ) from error

    def start(self, initial: DetectionResult, now: datetime, monotonic_seconds: float) -> None:
        with self._lock:
            if self._current is not None:
                raise StorageError("session logger already started")
            self._require_offset(now)
            self._prepare_session_directory()
            self._append_event(
                now,
                {
                    "event_type": "session_start",
                    "status": initial.status.value,
                    "confidence": initial.confidence,
                    "reason": initial.reason,
                    "metrics": dict(initial.metrics),
                },
            )
            self._current = initial
            self._started_at = now
            self._started_monotonic = monotonic_seconds
            self._session_started_at = now
            self._write_session_summary(now, monotonic_seconds)

    def transition(self, result: DetectionResult, now: datetime, monotonic_seconds: float) -> None:
        with self._lock:
            current, started_at, started_monotonic = self._require_active()
            if result.status is current.status:
                return

            elapsed = max(0.0, monotonic_seconds - started_monotonic)
            self._session_status_seconds[current.status.value] += elapsed
            affected_days = self._append_duration(
                started_at,
                now,
                elapsed,
                current,
                {
                    "event_type": "status_transition",
                    "status": result.status.value,
                    "confidence": result.confidence,
                    "reason": result.reason,
                    "metrics": dict(result.metrics),
                },
            )
            self._current = result
            self._started_at = now
            self._started_monotonic = monotonic_seconds
            self._session_transition_count += 1
            self._rebuild_days(affected_days, now)
            self._write_session_summary(now, monotonic_seconds)

    def checkpoint(self, now: datetime, monotonic_seconds: float) -> None:
        """Close the current daily segment after the local date changes."""
        with self._lock:
            current, started_at, started_monotonic = self._require_active()
            if started_at.date() == now.date():
                return

            elapsed = max(0.0, monotonic_seconds - started_monotonic)
            self._session_status_seconds[current.status.value] += elapsed
            affected_days = self._append_duration(
                started_at,
                now,
                elapsed,
                current,
                {
                    "event_type": "daily_checkpoint",
                    "status": current.status.value,
                    "confidence": current.confidence,
                    "reason": current.reason,
                    "metrics": dict(current.metrics),
                },
            )
            self._started_at = now
            self._started_monotonic = monotonic_seconds
            self._rebuild_days(affected_days, now)
            self._write_session_summary(now, monotonic_seconds)

    def close(self, now: datetime, monotonic_seconds: float) -> None:
        with self._lock:
            if self._closed:
                return
            if self._current is None:
                self._closed = True
                return

            current, started_at, started_monotonic = self._require_active()
            elapsed = max(0.0, monotonic_seconds - started_monotonic)
            self._session_status_seconds[current.status.value] += elapsed
            affected_days = self._append_duration(
                started_at,
                now,
                elapsed,
                current,
                {
                    "event_type": "session_end",
                    "status": current.status.value,
                    "confidence": current.confidence,
                    "reason": current.reason,
                    "metrics": dict(current.metrics),
                },
            )
            self._rebuild_days(affected_days, now)
            self._session_ended_at = now
            self._closed = True
            self._write_session_summary(now, monotonic_seconds)

    def snapshot(self, day: date, now: datetime, monotonic_seconds: float) -> DailyMetrics:
        """Return saved totals plus the open segment without changing the log."""
        with self._lock:
            seconds_by_status = self._read_status_seconds(day)
            if self._current is not None and not self._closed:
                current, started_at, started_monotonic = self._require_active()
                elapsed = max(0.0, monotonic_seconds - started_monotonic)
                for slice_day, slice_seconds in _split_duration_by_day(started_at, now, elapsed):
                    if slice_day == day:
                        seconds_by_status[current.status.value] += slice_seconds
            return calculate_daily_metrics(day, seconds_by_status)

    def session_snapshot(self, now: datetime, monotonic_seconds: float) -> SessionMetrics | None:
        with self._lock:
            if self._session_started_at is None or self._current is None:
                return None
            seconds_by_status = dict(self._session_status_seconds)
            if not self._closed and self._started_monotonic is not None:
                elapsed = max(0.0, monotonic_seconds - self._started_monotonic)
                seconds_by_status[self._current.status.value] += elapsed
            return calculate_session_metrics(
                self._session_id,
                self._session_started_at,
                self._session_ended_at,
                not self._closed,
                self._current,
                self._session_transition_count,
                self._diagnostic_output_enabled,
                self._diagnostic_frame_count,
                seconds_by_status,
            )

    def record_diagnostic_frame(self) -> None:
        with self._lock:
            if self._closed or self._session_started_at is None:
                raise StorageError("cannot add a diagnostic frame outside an active session")
            self._diagnostic_frame_count += 1

    def rebuild_summary(
        self,
        day: date,
        generated_at: datetime | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            metrics = calculate_daily_metrics(day, self._read_status_seconds(day))
            summary = {
                "schema_version": self.schema_version,
                "generated_at": (generated_at or datetime.now().astimezone()).isoformat(),
                **metrics.to_mapping(),
            }
            self._write_summary_atomic(day, summary)
            return summary

    def list_session_summaries(self) -> tuple[dict[str, Any], ...]:
        sessions_path = self._data_dir / "sessions"
        if not sessions_path.exists():
            return ()
        summaries: list[dict[str, Any]] = []
        with self._lock:
            for summary_path in sessions_path.glob("*/summary.json"):
                try:
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                    started_at = datetime.fromisoformat(summary["started_at"])
                    session_id = str(summary["session_id"])
                except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
                summary["session_id"] = session_id
                summary["session_directory"] = str(summary_path.parent)
                summary["_started_at_sort"] = started_at.timestamp()
                summaries.append(summary)
        summaries.sort(key=lambda item: float(item["_started_at_sort"]), reverse=True)
        for summary in summaries:
            summary.pop("_started_at_sort", None)
        return tuple(summaries)

    def recover_interrupted_sessions(
        self,
        recovered_at: datetime | None = None,
    ) -> tuple[Path, ...]:
        """Close stale active summaries after the caller acquires the data lock."""

        recovery_time = recovered_at or datetime.now().astimezone()
        self._require_offset(recovery_time)
        sessions_path = self._data_dir / "sessions"
        if not sessions_path.exists():
            return ()

        recovered: list[Path] = []
        with self._lock:
            for summary_path in sorted(sessions_path.glob("*/summary.json")):
                try:
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(summary, dict) or summary.get("state") != "active":
                    continue
                last_update = summary.get("generated_at")
                if not isinstance(last_update, str):
                    last_update = recovery_time.isoformat()
                summary["generated_at"] = recovery_time.isoformat()
                summary["ended_at"] = last_update
                summary["state"] = "interrupted"
                self._write_json_atomic(
                    summary_path,
                    summary,
                    description="interrupted session summary",
                )
                recovered.append(summary_path)
        return tuple(recovered)

    def prune(self, retention_days: int, today: date | None = None) -> tuple[Path, ...]:
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        cutoff = (today or datetime.now().astimezone().date()) - timedelta(days=retention_days - 1)
        removed: list[Path] = []
        with self._lock:
            for path in self._history_paths():
                file_day = _history_day(path)
                if file_day is not None and file_day < cutoff:
                    try:
                        path.unlink()
                    except OSError as error:
                        raise StorageError(f"cannot delete history file {path}: {error}") from error
                    removed.append(path)
            sessions_path = self._data_dir / "sessions"
            if sessions_path.exists():
                for session_path in sorted(sessions_path.iterdir()):
                    session_day = _session_history_day(session_path)
                    if session_day is None or session_day >= cutoff:
                        continue
                    try:
                        shutil.rmtree(session_path)
                    except OSError as error:
                        raise StorageError(
                            f"cannot delete expired session {session_path}: {error}"
                        ) from error
                    removed.append(session_path)
        return tuple(removed)

    def delete_history(self) -> tuple[Path, ...]:
        with self._lock:
            if self._current is not None and not self._closed:
                raise StorageError("stop tracking before you delete history")
            removed: list[Path] = []
            for path in self._history_paths():
                try:
                    path.unlink()
                except OSError as error:
                    raise StorageError(f"cannot delete history file {path}: {error}") from error
                removed.append(path)
            sessions_path = self._data_dir / "sessions"
            if sessions_path.exists():
                try:
                    shutil.rmtree(sessions_path)
                except OSError as error:
                    raise StorageError(
                        f"cannot delete session history {sessions_path}: {error}"
                    ) from error
                removed.append(sessions_path)
            return tuple(removed)

    def _append_duration(
        self,
        started_at: datetime,
        ended_at: datetime,
        elapsed: float,
        previous: DetectionResult,
        final_payload: dict[str, Any],
    ) -> set[date]:
        affected_days: set[date] = set()
        slices = _split_duration_by_day(started_at, ended_at, elapsed)
        for index, (event_day, slice_seconds) in enumerate(slices):
            is_final = index == len(slices) - 1
            payload = (
                dict(final_payload)
                if is_final
                else {
                    "event_type": "daily_checkpoint",
                    "status": previous.status.value,
                    "confidence": previous.confidence,
                    "reason": previous.reason,
                    "metrics": dict(previous.metrics),
                }
            )
            payload["previous_status"] = previous.status.value
            payload["elapsed_previous_seconds"] = slice_seconds
            self._append_event(ended_at, payload, event_day=event_day)
            affected_days.add(event_day)
        return affected_days

    def _rebuild_days(self, days: set[date], generated_at: datetime) -> None:
        for affected_day in sorted(days):
            self.rebuild_summary(affected_day, generated_at=generated_at)

    def _require_active(self) -> tuple[DetectionResult, datetime, float]:
        if self._closed:
            raise StorageError("session logger is closed")
        if self._current is None or self._started_at is None or self._started_monotonic is None:
            raise StorageError("session logger is not started")
        return self._current, self._started_at, self._started_monotonic

    def _append_event(
        self,
        now: datetime,
        payload: dict[str, Any],
        *,
        event_day: date | None = None,
    ) -> None:
        self._require_offset(now)
        event = {
            "schema_version": self.schema_version,
            "timestamp": now.isoformat(),
            "session_id": self._session_id,
            "model_version": self._model_version,
            "configuration_version": self._configuration_version,
            **payload,
        }
        path = self._event_path(event_day or now.date())
        encoded = (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")
        flags = os.O_APPEND | os.O_CREAT | os.O_RDWR
        try:
            descriptor = os.open(path, flags, 0o600)
            with os.fdopen(descriptor, "ab") as stream:
                size = os.fstat(stream.fileno()).st_size
                separator = b""
                if size > 0:
                    os.lseek(stream.fileno(), -1, os.SEEK_END)
                    if os.read(stream.fileno(), 1) != b"\n":
                        separator = b"\n"
                stream.write(separator + encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            raise StorageError(f"cannot write event log {path}: {error}") from error

    def _read_status_seconds(self, day: date) -> dict[str, float]:
        seconds_by_status = {status.value: 0.0 for status in Status}
        event_path = self._event_path(day)
        if not event_path.exists():
            return seconds_by_status
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
        return seconds_by_status

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

    def _prepare_session_directory(self) -> None:
        try:
            self._session_directory.mkdir(parents=True, exist_ok=False, mode=0o700)
            os.chmod(self._session_directory.parent, 0o700)
            os.chmod(self._session_directory, 0o700)
        except OSError as error:
            raise StorageError(
                f"cannot prepare session directory {self._session_directory}: {error}"
            ) from error

    def _write_session_summary(
        self,
        generated_at: datetime,
        monotonic_seconds: float,
    ) -> None:
        metrics = self.session_snapshot(generated_at, monotonic_seconds)
        if metrics is None:
            return
        destination = self._session_directory / "summary.json"
        summary = {
            "schema_version": self.schema_version,
            "generated_at": generated_at.isoformat(),
            "model_version": self._model_version,
            "configuration_version": self._configuration_version,
            **metrics.to_mapping(),
        }
        self._write_json_atomic(destination, summary, description="session summary")

    @staticmethod
    def _write_json_atomic(
        destination: Path,
        values: dict[str, Any],
        *,
        description: str,
    ) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                json.dump(values, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, destination)
        except OSError as error:
            raise StorageError(f"cannot write {description} {destination}: {error}") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _history_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted((*self._data_dir.glob("events-*.jsonl"), *self._data_dir.glob("summary-*.json")))
        )

    def _event_path(self, day: date) -> Path:
        return self._data_dir / f"events-{day.isoformat()}.jsonl"

    def _summary_path(self, day: date) -> Path:
        return self._data_dir / f"summary-{day.isoformat()}.json"

    @staticmethod
    def _require_offset(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise StorageError("event timestamps must include a UTC offset")


def _split_duration_by_day(
    started_at: datetime,
    ended_at: datetime,
    elapsed_seconds: float,
) -> tuple[tuple[date, float], ...]:
    if elapsed_seconds <= 0.0 or started_at.date() == ended_at.date():
        return ((ended_at.date(), max(0.0, elapsed_seconds)),)

    boundaries = [started_at]
    next_day = started_at.date() + timedelta(days=1)
    while next_day <= ended_at.date():
        timezone = ended_at.tzinfo if next_day == ended_at.date() else started_at.tzinfo
        boundaries.append(datetime.combine(next_day, time.min, tzinfo=timezone))
        next_day += timedelta(days=1)
    boundaries.append(ended_at)

    wall_seconds = [
        max(0.0, (end - start).total_seconds())
        for start, end in zip(boundaries, boundaries[1:], strict=False)
    ]
    total_wall_seconds = sum(wall_seconds)
    if total_wall_seconds <= 0.0:
        return ((ended_at.date(), elapsed_seconds),)

    slices: list[tuple[date, float]] = []
    allocated = 0.0
    for index, seconds in enumerate(wall_seconds):
        slice_seconds = (
            elapsed_seconds - allocated
            if index == len(wall_seconds) - 1
            else elapsed_seconds * seconds / total_wall_seconds
        )
        slices.append((boundaries[index].date(), max(0.0, slice_seconds)))
        allocated += slice_seconds
    return tuple(slices)


def _history_day(path: Path) -> date | None:
    name = path.name
    prefix = (
        "events-"
        if name.startswith("events-")
        else "summary-"
        if name.startswith("summary-")
        else None
    )
    if prefix is None:
        return None
    suffix = ".jsonl" if prefix == "events-" else ".json"
    with suppress(ValueError):
        return date.fromisoformat(name.removeprefix(prefix).removesuffix(suffix))
    return None


def _session_history_day(path: Path) -> date | None:
    if not path.is_dir():
        return None
    summary_path = path / "summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        started_at = datetime.fromisoformat(summary["started_at"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    return started_at.date()
