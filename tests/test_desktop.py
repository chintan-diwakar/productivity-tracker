from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from know_your_focus.config import load_config
from know_your_focus.desktop import STATUS_LABELS, DesktopBusyError, DesktopController
from know_your_focus.domain import Status


class DesktopLabelsTest(unittest.TestCase):
    def test_has_a_user_facing_label_for_every_status(self) -> None:
        self.assertEqual(set(STATUS_LABELS), set(Status))
        self.assertEqual(STATUS_LABELS[Status.POSSIBLE_PHONE_USE], "Possible phone use")


class DesktopCameraOperationTest(unittest.TestCase):
    def test_rejects_overlapping_camera_operations(self) -> None:
        with TemporaryDirectory() as directory:
            controller = DesktopController(Path(directory) / "configuration.json")

            with (
                controller._camera_operation("camera preview"),
                self.assertRaisesRegex(DesktopBusyError, "camera preview is active"),
                controller._camera_operation("starting tracking"),
            ):
                self.fail("overlapping operation unexpectedly started")

    def test_releases_camera_after_an_operation_fails(self) -> None:
        with TemporaryDirectory() as directory:
            controller = DesktopController(Path(directory) / "configuration.json")

            with (
                self.assertRaisesRegex(RuntimeError, "preview failed"),
                controller._camera_operation("camera preview"),
            ):
                raise RuntimeError("preview failed")

            with controller._camera_operation("starting tracking"):
                pass

    def test_unchanged_camera_setting_does_not_stop_tracking(self) -> None:
        with TemporaryDirectory() as directory:
            controller = DesktopController(Path(directory) / "configuration.json")

            with patch.object(controller, "stop") as stop:
                controller.save_camera_index(0)

            stop.assert_not_called()

    def test_changed_camera_setting_stops_tracking_before_save(self) -> None:
        with TemporaryDirectory() as directory:
            controller = DesktopController(Path(directory) / "configuration.json")

            with patch.object(controller, "stop") as stop:
                controller.save_camera_index(1)

            stop.assert_called_once_with()
            self.assertEqual(controller.config.camera_index, 1)

    def test_saves_diagnostic_setting_for_the_next_session(self) -> None:
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "configuration.json"
            controller = DesktopController(config_path)

            controller.save_diagnostic_setting(True)

            self.assertTrue(controller.config.save_diagnostic_frames)
            self.assertTrue(load_config(config_path).save_diagnostic_frames)


if __name__ == "__main__":
    unittest.main()
