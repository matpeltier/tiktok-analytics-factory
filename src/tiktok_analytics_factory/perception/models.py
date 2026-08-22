"""Typed models for deterministic perception artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


PIPELINE_VERSION = "perception_v1"


@dataclass
class Rational:
    """A frame-rate rational, e.g. 30000/1001."""

    numerator: int
    denominator: int

    def to_float(self) -> float:
        if self.denominator == 0:
            raise ZeroDivisionError("rational denominator is zero")
        return self.numerator / self.denominator

    def to_dict(self) -> dict[str, int]:
        return {"numerator": self.numerator, "denominator": self.denominator}


@dataclass
class MediaFacts:
    """Authoritative media facts probed with ffprobe."""

    video_path: str
    duration_seconds: float | None
    width: int | None
    height: int | None
    aspect_ratio: str | None
    fps_rational: str | None
    fps: float | None
    avg_fps_rational: str | None
    avg_fps: float | None
    frame_count: int | None
    video_codec: str | None
    audio_codec: str | None  # None when the audio stream is absent (valid fact)
    has_audio: bool
    container_format: str | None
    bit_rate: int | None
    file_size_bytes: int
    sha256: str
    ffprobe_version: str
    probe_command: list[str]
    probed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Shot:
    shot_id: str
    start_seconds: float
    end_seconds: float
    start_frame: int
    end_frame: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ShotDetectionResult:
    detector: str
    detector_version: str
    parameters: dict[str, Any]
    shots: list[Shot]

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "detector_version": self.detector_version,
            "parameters": self.parameters,
            "shots": [s.to_dict() for s in self.shots],
        }


@dataclass
class FrameArtifact:
    shot_id: str
    path: str
    timestamp_seconds: float
    frame_index: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DetectorConfig:
    """Deterministic scene-detector configuration."""

    threshold: float = 27.0
    min_scene_len_frames: int = 15
    downscale_factor: int | None = None  # None -> scenedetect default

    def to_parameters(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "min_scene_len_frames": self.min_scene_len_frames,
            "downscale_factor": self.downscale_factor,
        }


@dataclass
class PerceptionManifest:
    """Top-level perception artifact manifest."""

    pipeline_version: str
    video_id: str
    source_sha256: str
    processed_at: str
    media_facts: MediaFacts
    shots: ShotDetectionResult
    frames: list[FrameArtifact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_version": self.pipeline_version,
            "video_id": self.video_id,
            "source_sha256": self.source_sha256,
            "processed_at": self.processed_at,
            "media_facts": self.media_facts.to_dict(),
            "shots": self.shots.to_dict(),
            "frames": [f.to_dict() for f in self.frames],
        }
