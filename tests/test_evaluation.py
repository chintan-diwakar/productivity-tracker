from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from desk_focus_tracker.domain import Status
from desk_focus_tracker.evaluation import EvaluationError, evaluate_results, load_labeled_results


class EvaluationTest(unittest.TestCase):
    def test_calculates_phone_precision_and_uncertain_rate(self) -> None:
        results = [
            (Status.POSSIBLE_PHONE_USE, Status.POSSIBLE_PHONE_USE),
            (Status.POSSIBLE_PHONE_USE, Status.LOOKING_DOWN),
            (Status.FOCUSED_SCREEN, Status.POSSIBLE_PHONE_USE),
            (Status.FOCUSED_SCREEN, Status.FOCUSED_SCREEN),
        ]

        report = evaluate_results(results)

        phone = report["classes"]["POSSIBLE_PHONE_USE"]
        self.assertEqual(phone["precision"], 0.5)
        self.assertEqual(phone["recall"], 0.5)
        self.assertEqual(report["uncertain_rate"], 0.25)
        self.assertEqual(report["overall_accuracy"], 0.5)

    def test_loads_json_lines_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "labels.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "actual_status": "FOCUSED_SCREEN",
                        "predicted_status": "FOCUSED_SCREEN",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            records = load_labeled_results(path)

        self.assertEqual(records, [(Status.FOCUSED_SCREEN, Status.FOCUSED_SCREEN)])

    def test_rejects_an_unknown_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "labels.jsonl"
            path.write_text(
                '{"actual_status":"UNKNOWN","predicted_status":"FOCUSED_SCREEN"}\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(EvaluationError, "line 1"):
                load_labeled_results(path)


if __name__ == "__main__":
    unittest.main()
