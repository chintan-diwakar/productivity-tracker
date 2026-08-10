from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Raised when application configuration is invalid."""


def default_data_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "desk-focus-tracker"
    return Path.home() / ".local" / "share" / "desk-focus-tracker"


def default_model_dir() -> Path:
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        return Path(xdg_cache_home) / "desk-focus-tracker" / "models"
    return Path.home() / ".cache" / "desk-focus-tracker" / "models"


@dataclass(frozen=True, slots=True)
class AppConfig:
    camera_index: int = 0
    capture_fps: float = 1.0
    away_capture_fps: float = 0.2
    frame_width: int = 320
    frame_height: int = 240
    idle_timeout_seconds: float = 300.0
    away_timeout_seconds: float = 30.0
    window_samples: int = 5
    minimum_matching_samples: int = 3
    retention_days: int = 30
    data_dir: Path = Path("data")
    model_dir: Path = Path("models")
    detector_backend: str = "mediapipe"
    object_score_threshold: float = 0.35
    downward_pitch_threshold_degrees: float = 15.0
    neutral_head_pitch_degrees: float = 0.0
    head_pitch_sign: float = 1.0
    phone_hand_max_distance: float = 0.2
    configuration_version: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.data_dir, str):
            object.__setattr__(self, "data_dir", Path(self.data_dir).expanduser())
        if isinstance(self.model_dir, str):
            object.__setattr__(self, "model_dir", Path(self.model_dir).expanduser())

        errors: list[str] = []
        if self.camera_index < 0:
            errors.append("camera_index must be zero or greater")
        if not 0.0 < self.capture_fps <= 2.0:
            errors.append("capture_fps must be greater than 0.0 and not more than 2.0")
        if not 0.0 < self.away_capture_fps <= self.capture_fps:
            errors.append("away_capture_fps must be greater than 0.0 and not more than capture_fps")
        if self.frame_width <= 0 or self.frame_height <= 0:
            errors.append("frame dimensions must be positive")
        if self.idle_timeout_seconds < 0.0:
            errors.append("idle_timeout_seconds must be zero or greater")
        if self.away_timeout_seconds < 0.0:
            errors.append("away_timeout_seconds must be zero or greater")
        if self.window_samples <= 0:
            errors.append("window_samples must be positive")
        if not 0 < self.minimum_matching_samples <= self.window_samples:
            errors.append("minimum_matching_samples must be positive and not exceed window_samples")
        if self.retention_days <= 0:
            errors.append("retention_days must be positive")
        if self.detector_backend not in {"mediapipe", "opencv_face"}:
            errors.append(f"unsupported detector_backend: {self.detector_backend}")
        if not 0.0 <= self.object_score_threshold <= 1.0:
            errors.append("object_score_threshold must be between 0.0 and 1.0")
        if not 0.0 < self.downward_pitch_threshold_degrees <= 90.0:
            errors.append("downward_pitch_threshold_degrees must be greater than 0.0")
        if self.head_pitch_sign not in {-1.0, 1.0}:
            errors.append("head_pitch_sign must be -1.0 or 1.0")
        if not 0.0 < self.phone_hand_max_distance <= 1.0:
            errors.append("phone_hand_max_distance must be greater than 0.0 and not more than 1.0")
        if self.configuration_version <= 0:
            errors.append("configuration_version must be positive")
        if errors:
            raise ConfigurationError("; ".join(errors))

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> AppConfig:
        allowed = {field.name for field in fields(cls)}
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ConfigurationError(f"unknown configuration keys: {', '.join(unknown)}")

        normalized = dict(values)
        for path_key in ("data_dir", "model_dir"):
            if path_key not in normalized:
                continue
            value = normalized[path_key]
            if not isinstance(value, str) or not value:
                raise ConfigurationError(f"{path_key} must be a non-empty string")
            normalized[path_key] = Path(value).expanduser()

        try:
            return cls(**normalized)
        except TypeError as error:
            raise ConfigurationError(str(error)) from error

    def to_mapping(self) -> dict[str, Any]:
        values = asdict(self)
        values["data_dir"] = str(self.data_dir)
        values["model_dir"] = str(self.model_dir)
        return values


def load_config(path: Path | None) -> AppConfig:
    if path is None:
        return AppConfig(data_dir=default_data_dir(), model_dir=default_model_dir())

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigurationError(f"cannot read configuration {path}: {error}") from error

    try:
        values = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"invalid JSON in {path}: {error}") from error

    if not isinstance(values, dict):
        raise ConfigurationError("configuration root must be a JSON object")
    return AppConfig.from_mapping(values)


def write_default_config(path: Path) -> None:
    if path.exists():
        raise ConfigurationError(f"configuration already exists: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    config = AppConfig(data_dir=default_data_dir(), model_dir=default_model_dir())
    try:
        path.write_text(json.dumps(config.to_mapping(), indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        raise ConfigurationError(f"cannot write configuration {path}: {error}") from error
