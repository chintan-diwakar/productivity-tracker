from __future__ import annotations

import unittest

from desk_focus_tracker.domain import DetectionResult, Status
from desk_focus_tracker.policy import AwayPolicy


class AwayPolicyTest(unittest.TestCase):
    def test_waits_for_continuous_timeout(self) -> None:
        policy = AwayPolicy(timeout_seconds=30.0)
        absent = DetectionResult(Status.AWAY, 0.7, "no_face")

        first = policy.apply(absent, monotonic_seconds=100.0)
        before_timeout = policy.apply(absent, monotonic_seconds=129.9)
        after_timeout = policy.apply(absent, monotonic_seconds=130.0)

        self.assertIs(first.status, Status.UNCERTAIN)
        self.assertIs(before_timeout.status, Status.UNCERTAIN)
        self.assertIs(after_timeout.status, Status.AWAY)

    def test_visible_person_resets_timeout(self) -> None:
        policy = AwayPolicy(timeout_seconds=10.0)
        absent = DetectionResult(Status.AWAY, 0.7, "no_face")
        present = DetectionResult(Status.FOCUSED_SCREEN, 0.6, "face")

        policy.apply(absent, monotonic_seconds=0.0)
        policy.apply(present, monotonic_seconds=9.0)
        result = policy.apply(absent, monotonic_seconds=15.0)

        self.assertIs(result.status, Status.UNCERTAIN)


if __name__ == "__main__":
    unittest.main()
