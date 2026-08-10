from __future__ import annotations

import unittest

from desk_focus_tracker.domain import DetectionResult, Status
from desk_focus_tracker.smoothing import TemporalSmoother


class TemporalSmootherTest(unittest.TestCase):
    def test_changes_after_required_matching_samples(self) -> None:
        smoother = TemporalSmoother(window_samples=5, minimum_matching_samples=3)
        focused = DetectionResult(Status.FOCUSED_SCREEN, 0.6, "face")

        first = smoother.update(focused)
        second = smoother.update(focused)
        third = smoother.update(focused)

        self.assertFalse(first.changed)
        self.assertFalse(second.changed)
        self.assertTrue(third.changed)
        self.assertIs(third.stable.status, Status.FOCUSED_SCREEN)

    def test_ignores_one_frame_glitch(self) -> None:
        smoother = TemporalSmoother(window_samples=5, minimum_matching_samples=3)
        focused = DetectionResult(Status.FOCUSED_SCREEN, 0.6, "face")
        phone = DetectionResult(Status.POSSIBLE_PHONE_USE, 0.9, "phone")
        for _ in range(3):
            smoother.update(focused)

        result = smoother.update(phone)

        self.assertFalse(result.changed)
        self.assertIs(result.stable.status, Status.FOCUSED_SCREEN)


if __name__ == "__main__":
    unittest.main()
