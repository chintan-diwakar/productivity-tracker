from __future__ import annotations

import unittest

from desk_focus_tracker.idle import parse_idle_output


class IdleOutputTest(unittest.TestCase):
    def test_parses_gnome_idle_milliseconds(self) -> None:
        value = parse_idle_output("(uint64 12500,)", r"uint64\s+(\d+)", 1000.0)

        self.assertEqual(value, 12.5)

    def test_parses_macos_idle_nanoseconds(self) -> None:
        value = parse_idle_output('"HIDIdleTime" = 2500000000', r'"HIDIdleTime"\s*=\s*(\d+)', 1e9)

        self.assertEqual(value, 2.5)

    def test_returns_none_for_unknown_output(self) -> None:
        self.assertIsNone(parse_idle_output("unknown", r"(\d+)", 1000.0))


if __name__ == "__main__":
    unittest.main()
