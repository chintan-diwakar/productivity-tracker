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


if __name__ == "__main__":
    unittest.main()
