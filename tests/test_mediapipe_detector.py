from __future__ import annotations

import unittest

from know_your_focus.mediapipe_detector import _category_score_is_accepted


class CategoryScoreThresholdTest(unittest.TestCase):
    def test_keeps_low_confidence_phone_but_rejects_low_confidence_person(self) -> None:
        self.assertTrue(_category_score_is_accepted("cell phone", 0.20, 0.15, 0.35))
        self.assertFalse(_category_score_is_accepted("person", 0.20, 0.15, 0.35))
        self.assertTrue(_category_score_is_accepted("person", 0.40, 0.15, 0.35))


if __name__ == "__main__":
    unittest.main()
