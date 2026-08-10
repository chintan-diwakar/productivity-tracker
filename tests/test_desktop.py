from __future__ import annotations

import unittest

from desk_focus_tracker.desktop import STATUS_LABELS
from desk_focus_tracker.domain import Status


class DesktopLabelsTest(unittest.TestCase):
    def test_has_a_user_facing_label_for_every_status(self) -> None:
        self.assertEqual(set(STATUS_LABELS), set(Status))
        self.assertEqual(STATUS_LABELS[Status.POSSIBLE_PHONE_USE], "Possible phone use")


if __name__ == "__main__":
    unittest.main()
