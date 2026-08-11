from __future__ import annotations

import unittest

from know_your_focus.domain import DetectionResult, Status
from know_your_focus.smoothing import TemporalSmoother


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

    def test_preserves_metrics_on_transition(self) -> None:
        smoother = TemporalSmoother(window_samples=3, minimum_matching_samples=2)
        focused = DetectionResult(
            Status.FOCUSED_SCREEN,
            0.6,
            "face",
            (("head_pitch_degrees", 4.0),),
        )

        smoother.update(focused)
        result = smoother.update(focused)

        self.assertEqual(result.stable.metrics, focused.metrics)


if __name__ == "__main__":
    unittest.main()
