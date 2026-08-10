from __future__ import annotations

import unittest
from datetime import date

from desk_focus_tracker.metrics import calculate_daily_metrics, format_duration, format_ratio


class DailyMetricsTest(unittest.TestCase):
    def test_calculates_focus_ratio_and_coverage(self) -> None:
        metrics = calculate_daily_metrics(
            date(2026, 8, 10),
            {
                "FOCUSED_SCREEN": 60.0,
                "POSSIBLE_PHONE_USE": 20.0,
                "LOOKING_DOWN": 20.0,
                "AWAY": 50.0,
            },
        )

        self.assertEqual(metrics.focused_active_ratio, 0.75)
        self.assertEqual(metrics.classified_coverage, 0.8)
        self.assertEqual(metrics.classified_seconds, 80.0)
        self.assertEqual(metrics.observed_seconds, 100.0)
        self.assertEqual(metrics.tracked_seconds, 150.0)

    def test_reports_no_ratio_without_classified_time(self) -> None:
        metrics = calculate_daily_metrics(date(2026, 8, 10), {"AWAY": 10.0})

        self.assertIsNone(metrics.focused_active_ratio)
        self.assertIsNone(metrics.classified_coverage)

    def test_formats_user_facing_values(self) -> None:
        self.assertEqual(format_duration(3665.0), "1h 01m")
        self.assertEqual(format_duration(65.0), "1m 05s")
        self.assertEqual(format_ratio(0.756), "76%")
        self.assertEqual(format_ratio(None), "Not enough data")


if __name__ == "__main__":
    unittest.main()
