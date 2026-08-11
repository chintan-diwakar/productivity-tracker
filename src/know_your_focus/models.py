from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


class ModelError(RuntimeError):
    """Raised when a required model is absent or invalid."""


@dataclass(frozen=True, slots=True)
class ModelAsset:
    name: str
    filename: str
    url: str
    sha256: str


MODEL_SET_VERSION = "mediapipe-2026-08-10"

OBJECT_DETECTOR_MODEL = ModelAsset(
    name="EfficientDet-Lite0 INT8",
    filename="efficientdet_lite0.tflite",
    url=(
        "https://storage.googleapis.com/mediapipe-models/object_detector/"
        "efficientdet_lite0/int8/1/efficientdet_lite0.tflite"
    ),
    sha256="0720bf247bd76e6594ea28fa9c6f7c5242be774818997dbbeffc4da460c723bb",
)

FACE_LANDMARKER_MODEL = ModelAsset(
    name="Face Landmarker float16",
    filename="face_landmarker.task",
    url=(
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task"
    ),
    sha256="64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
)

HAND_LANDMARKER_MODEL = ModelAsset(
    name="Hand Landmarker float16",
    filename="hand_landmarker.task",
    url=(
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
        "hand_landmarker/float16/1/hand_landmarker.task"
    ),
    sha256="fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1",
)

MODEL_ASSETS = (
    OBJECT_DETECTOR_MODEL,
    FACE_LANDMARKER_MODEL,
    HAND_LANDMARKER_MODEL,
)

UrlOpener = Callable[..., BinaryIO]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise ModelError(f"cannot read model {path}: {error}") from error
    return digest.hexdigest()


class ModelStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, asset: ModelAsset) -> Path:
        return self.directory / asset.filename

    def require_all(self) -> None:
        errors: list[str] = []
        for asset in MODEL_ASSETS:
            path = self.path_for(asset)
            if not path.is_file():
                errors.append(f"missing {asset.name}: {path}")
                continue
            actual_sha256 = sha256_file(path)
            if actual_sha256 != asset.sha256:
                errors.append(f"invalid checksum for {asset.name}: {path}")
        if errors:
            command = f"kyf download-models --directory {self.directory}"
            raise ModelError("; ".join(errors) + f". Run: {command}")

    def download_all(self, force: bool = False) -> list[Path]:
        return [self.download(asset, force=force) for asset in MODEL_ASSETS]

    def download(
        self,
        asset: ModelAsset,
        force: bool = False,
        opener: UrlOpener = urllib.request.urlopen,
    ) -> Path:
        destination = self.path_for(asset)
        if destination.is_file():
            if sha256_file(destination) == asset.sha256:
                return destination
            if not force:
                raise ModelError(
                    f"model checksum does not match: {destination}. Use --force to replace it"
                )

        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ModelError(f"cannot create model directory {self.directory}: {error}") from error

        temporary_path: Path | None = None
        digest = hashlib.sha256()
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.directory,
                prefix=f".{asset.filename}.",
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                with opener(asset.url, timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                        digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())

            if digest.hexdigest() != asset.sha256:
                raise ModelError(f"downloaded model checksum does not match: {asset.name}")
            os.chmod(temporary_path, 0o644)
            os.replace(temporary_path, destination)
            return destination
        except (OSError, urllib.error.URLError) as error:
            raise ModelError(f"cannot download {asset.name}: {error}") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
