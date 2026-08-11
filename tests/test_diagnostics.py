from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from know_your_focus.diagnostics import DiagnosticFrameWriter
from know_your_focus.domain import DetectionResult, Status


class DiagnosticFrameWriterTest(unittest.TestCase):
    def test_saves_annotated_frame_and_manifest_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_directory = Path(temporary_directory) / "session"
            writer = DiagnosticFrameWriter(session_directory, frame_limit=2)
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
            result = DetectionResult(
                Status.POSSIBLE_PHONE_USE,
                0.8,
                "phone_near_hand_and_downward_head_pose",
                (("phone_count", 1.0),),
            )

            saved = writer.capture(
                frame,
                result,
                datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
            )

            diagnostic_directory = session_directory / "diagnostics"
            images = tuple(diagnostic_directory.glob("*.jpg"))
            manifest = [
                json.loads(line)
                for line in (diagnostic_directory / "manifest.jsonl").read_text().splitlines()
            ]

        self.assertTrue(saved)
        self.assertEqual(len(images), 1)
        self.assertEqual(manifest[0]["status"], Status.POSSIBLE_PHONE_USE.value)
        self.assertEqual(manifest[0]["metrics"]["phone_count"], 1.0)

    def test_stops_after_frame_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            writer = DiagnosticFrameWriter(Path(temporary_directory), frame_limit=1)
            frame = np.zeros((20, 20, 3), dtype=np.uint8)
            result = DetectionResult(Status.FOCUSED_SCREEN, 0.8, "focused")
            captured_at = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)

            first_saved = writer.capture(frame, result, captured_at)
            second_saved = writer.capture(frame, result, captured_at)

        self.assertTrue(first_saved)
        self.assertFalse(second_saved)
        self.assertTrue(writer.limit_reached)
        self.assertEqual(writer.frame_count, 1)


if __name__ == "__main__":
    unittest.main()
