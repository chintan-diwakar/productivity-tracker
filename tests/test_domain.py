from __future__ import annotations

import unittest

from desk_focus_tracker.domain import StatisticsCategory, Status, statistics_category


class StatisticsCategoryTest(unittest.TestCase):
    def test_maps_statuses_to_statistics_categories(self) -> None:
        expected = {
            Status.FOCUSED_SCREEN: StatisticsCategory.PRODUCTIVE,
            Status.POSSIBLE_PHONE_USE: StatisticsCategory.UNPRODUCTIVE,
            Status.LOOKING_DOWN: StatisticsCategory.UNCERTAIN,
            Status.LOOKING_AWAY: StatisticsCategory.UNCERTAIN,
            Status.UNCERTAIN: StatisticsCategory.UNCERTAIN,
            Status.AWAY: StatisticsCategory.EXCLUDED,
            Status.SYSTEM_IDLE: StatisticsCategory.EXCLUDED,
            Status.PAUSED: StatisticsCategory.EXCLUDED,
            Status.CAMERA_ERROR: StatisticsCategory.EXCLUDED,
        }

        actual = {status: statistics_category(status) for status in Status}

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
