from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from desk_focus_tracker.domain import DetectionResult, Status
from desk_focus_tracker.storage import JsonlSessionLogger


class JsonlSessionLoggerTest(unittest.TestCase):
    def test_writes_events_and_rebuilds_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory)
            logger = JsonlSessionLogger(data_dir, "test-model", 1)
            started_at = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
            focused = DetectionResult(
                Status.FOCUSED_SCREEN,
                0.8,
                "focused",
                (("head_pitch_degrees", 2.5),),
            )
            phone = DetectionResult(Status.POSSIBLE_PHONE_USE, 0.9, "phone")

            logger.start(focused, started_at, monotonic_seconds=100.0)
            logger.transition(phone, started_at + timedelta(seconds=10), 110.0)
            logger.close(started_at + timedelta(seconds=15), 115.0)

            event_path = data_dir / "events-2026-08-10.jsonl"
            summary_path = data_dir / "summary-2026-08-10.json"
            events = [json.loads(line) for line in event_path.read_text().splitlines()]
            summary = json.loads(summary_path.read_text())

        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]["metrics"]["head_pitch_degrees"], 2.5)
        self.assertEqual(summary["status_seconds"]["FOCUSED_SCREEN"], 10.0)
        self.assertEqual(summary["status_seconds"]["POSSIBLE_PHONE_USE"], 5.0)
        self.assertEqual(summary["productive_ratio"], 2 / 3)

    def test_ignores_incomplete_final_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory)
            logger = JsonlSessionLogger(data_dir, "test-model", 1)
            day = datetime(2026, 8, 10, tzinfo=timezone.utc).date()
            event_path = data_dir / "events-2026-08-10.jsonl"
            event_path.write_text(
                '{"previous_status":"FOCUSED_SCREEN","elapsed_previous_seconds":4}\n{',
                encoding="utf-8",
            )

            summary = logger.rebuild_summary(day)

        self.assertEqual(summary["status_seconds"]["FOCUSED_SCREEN"], 4.0)

    def test_splits_a_segment_at_local_midnight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory)
            logger = JsonlSessionLogger(data_dir, "test-model", 1)
            started_at = datetime(2026, 8, 10, 23, 59, 50, tzinfo=timezone.utc)
            focused = DetectionResult(Status.FOCUSED_SCREEN, 0.8, "focused")
            phone = DetectionResult(Status.POSSIBLE_PHONE_USE, 0.9, "phone")

            logger.start(focused, started_at, monotonic_seconds=100.0)
            logger.transition(phone, started_at + timedelta(seconds=20), 120.0)

            first_day = logger.rebuild_summary(started_at.date())
            second_day = logger.rebuild_summary((started_at + timedelta(days=1)).date())

        self.assertEqual(first_day["status_seconds"]["FOCUSED_SCREEN"], 10.0)
        self.assertEqual(second_day["status_seconds"]["FOCUSED_SCREEN"], 10.0)

    def test_snapshot_includes_the_open_segment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            logger = JsonlSessionLogger(Path(temporary_directory), "test-model", 1)
            started_at = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
            focused = DetectionResult(Status.FOCUSED_SCREEN, 0.8, "focused")
            logger.start(focused, started_at, monotonic_seconds=100.0)

            metrics = logger.snapshot(
                started_at.date(),
                started_at + timedelta(seconds=15),
                monotonic_seconds=115.0,
            )

        self.assertEqual(metrics.status_seconds["FOCUSED_SCREEN"], 15.0)
        self.assertEqual(metrics.focused_active_ratio, 1.0)

    def test_prunes_only_expired_history_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory)
            logger = JsonlSessionLogger(data_dir, "test-model", 1)
            old_event = data_dir / "events-2026-08-01.jsonl"
            recent_summary = data_dir / "summary-2026-08-10.json"
            unrelated = data_dir / "notes.json"
            for path in (old_event, recent_summary, unrelated):
                path.write_text("{}", encoding="utf-8")

            removed = logger.prune(7, today=datetime(2026, 8, 10).date())

            self.assertEqual(removed, (old_event,))
            self.assertFalse(old_event.exists())
            self.assertTrue(recent_summary.exists())
            self.assertTrue(unrelated.exists())


if __name__ == "__main__":
    unittest.main()
