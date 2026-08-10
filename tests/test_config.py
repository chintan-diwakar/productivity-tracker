from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from desk_focus_tracker.config import (
    AppConfig,
    ConfigurationError,
    load_config,
    write_config,
)


class AppConfigTest(unittest.TestCase):
    def test_loads_json_and_converts_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "configuration.json"
            path.write_text(
                json.dumps({"capture_fps": 0.5, "data_dir": "~/desk-focus-data"}),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.capture_fps, 0.5)
        self.assertEqual(config.data_dir, Path("~/desk-focus-data").expanduser())

    def test_rejects_unknown_key(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "unknown configuration keys"):
            AppConfig.from_mapping({"unknown": True})

    def test_rejects_invalid_smoothing_threshold(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "minimum_matching_samples"):
            AppConfig(window_samples=3, minimum_matching_samples=4)

    def test_rejects_invalid_diagnostic_frame_limit(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "diagnostic_frame_limit"):
            AppConfig(diagnostic_frame_limit=0)

    def test_uses_separate_phone_and_person_thresholds(self) -> None:
        config = AppConfig()

        self.assertEqual(config.object_score_threshold, 0.15)
        self.assertEqual(config.person_score_threshold, 0.35)

    def test_converts_direct_path_strings(self) -> None:
        config = AppConfig(data_dir="~/data", model_dir="~/models")

        self.assertEqual(config.data_dir, Path("~/data").expanduser())
        self.assertEqual(config.model_dir, Path("~/models").expanduser())

    def test_writes_configuration_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "configuration.json"
            write_config(path, replace(AppConfig(), camera_index=2))

            config = load_config(path)

        self.assertEqual(config.camera_index, 2)


if __name__ == "__main__":
    unittest.main()
