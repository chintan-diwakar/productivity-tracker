from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from desk_focus_tracker.instance_lock import InstanceLock, InstanceLockError


class InstanceLockTest(unittest.TestCase):
    def test_rejects_a_second_owner_and_allows_it_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_path = Path(temporary_directory) / "tracker.lock"
            first = InstanceLock(lock_path)
            second = InstanceLock(lock_path)

            first.acquire()
            with self.assertRaisesRegex(InstanceLockError, "already running"):
                second.acquire()
            first.release()
            second.acquire()
            second.release()

    def test_context_manager_writes_the_process_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock_path = Path(temporary_directory) / "tracker.lock"

            with InstanceLock(lock_path):
                self.assertTrue(lock_path.read_text(encoding="ascii").strip().isdigit())


if __name__ == "__main__":
    unittest.main()
