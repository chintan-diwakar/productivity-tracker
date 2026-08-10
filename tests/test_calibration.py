from __future__ import annotations

import unittest

from desk_focus_tracker.calibration import CalibrationError, calculate_neutral_pitch


class CalibrationTest(unittest.TestCase):
    def test_uses_the_median_pitch_and_deviation(self) -> None:
        neutral, spread = calculate_neutral_pitch((3.0, 4.0, 5.0, 30.0))

        self.assertEqual(neutral, 4.5)
        self.assertEqual(spread, 1.0)

    def test_requires_three_samples(self) -> None:
        with self.assertRaisesRegex(CalibrationError, "three"):
            calculate_neutral_pitch((1.0, 2.0))


if __name__ == "__main__":
    unittest.main()
