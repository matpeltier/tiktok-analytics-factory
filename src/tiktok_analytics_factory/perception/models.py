"""Typed schemas for the deterministic perception layer.

All persisted artifacts are serialized from these dataclasses; consumers of
``media_facts.json`` / ``shots.json`` never parse unvalidated dicts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PIPELINE_VERSION = "v1"


@dataclass
class PerceptionConfig:
    """Detector configuration. Detector parameters are part of provenance."""

    detector: str = "ContentDetector"
    threshold: float = 27.0
    min_scene_len_frames: int = 15
    downscale_factor: int | None = 4
    boundary_tolerance_seconds: float = 0.30

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "parameters": {
                "threshold": self.threshold,
                "min_scene_len_frames": self.min_scene_len_frames,
                "downscale_factor": self.downscale_factor,
            },
        }


@dataclass
class MediaFacts:
    """Authoritative media facts probed with ffprobe."""

    duration_seconds: float
    width: int
    height: int
    aspect_ratio_label: str  # e.g. "9:16" (reduced) or raw display ratio
    aspect_ratio_float: float
    fps_rational: str  # e.g. "30000/1001"
    fps: float
    frame_count: int | None
    video_codec: str
    audio_codec: str | None  # None when the source has no audio stream (valid)
    has_audio: bool
    container_format: str
    bit_rate: int | None
    file_size_bytes: int
    sha256: str
    ffprobe_version: str
    probed_at: str  # ISO-8601 UTC

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Shot:
    """A contiguous shot between hard cuts."""

    shot_id: str  # stable: "shot_001", "shot_002", ...
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
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "detector_version": self.detector_version,
            "parameters": self.parameters,
            "shots": [s.to_dict() for s in self.shots],
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class FrameArtifact:
    """One representative frame extracted deterministically for a shot."""

    shot_id: str
    path: str  # relative to output_dir
    timestamp_seconds: float
    width: int | None = None
    height: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PerceptionManifest:
    """Top-level manifest tying together all perception artifacts."""

    pipeline_version: str
    video_sha256: str
    generated_at: str
    config: dict[str, Any]
    media_facts: MediaFacts
    shots: ShotDetectionResult
    frames: list[FrameArtifact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_version": self.pipeline_version,
            "video_sha256": self.video_sha256,
            "generated_at": self.generated_at,
            "config": self.config,
            "media_facts": self.media_facts.to_dict(),
            "shots": self.shots.to_dict(),
            "frames": [f.to_dict() for f in self.frames],
        }
