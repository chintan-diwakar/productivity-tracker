from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from know_your_focus.models import ModelAsset, ModelError, ModelStore


class ModelStoreTest(unittest.TestCase):
    def test_downloads_and_verifies_asset(self) -> None:
        content = b"model bytes"
        asset = ModelAsset(
            name="test model",
            filename="test.task",
            url="https://example.invalid/test.task",
            sha256=hashlib.sha256(content).hexdigest(),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            store = ModelStore(Path(temporary_directory))

            path = store.download(asset, opener=lambda *_args, **_kwargs: io.BytesIO(content))

            self.assertEqual(path.read_bytes(), content)

    def test_rejects_invalid_download_checksum(self) -> None:
        asset = ModelAsset(
            name="test model",
            filename="test.task",
            url="https://example.invalid/test.task",
            sha256=hashlib.sha256(b"expected").hexdigest(),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            store = ModelStore(Path(temporary_directory))
            with self.assertRaisesRegex(ModelError, "checksum"):
                store.download(
                    asset,
                    opener=lambda *_args, **_kwargs: io.BytesIO(b"different"),
                )

            self.assertFalse(store.path_for(asset).exists())

    def test_does_not_download_valid_existing_asset(self) -> None:
        content = b"model bytes"
        asset = ModelAsset(
            name="test model",
            filename="test.task",
            url="https://example.invalid/test.task",
            sha256=hashlib.sha256(content).hexdigest(),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            store = ModelStore(Path(temporary_directory))
            path = store.path_for(asset)
            path.write_bytes(content)

            result = store.download(
                asset,
                opener=lambda *_args, **_kwargs: self.fail("unexpected download"),
            )

            self.assertEqual(result, path)


if __name__ == "__main__":
    unittest.main()
