"""Deterministic perception layer: media facts, shot boundaries, frames.

No VLM/OCR/transcription dependency. Facts a model should not guess come from
ffprobe and PySceneDetect.
"""

from .errors import (
    FFprobeUnavailableError,
    FrameExtractionError,
    MediaFileNotFoundError,
    NoVideoStreamError,
    PerceptionError,
    SceneDetectorUnavailableError,
    UnreadableMediaError,
)
from .evaluation import BoundaryEvaluation, CutAnnotation, evaluate_boundaries
from .frames import extract_representative_frames
from .models import (
    DetectorConfig,
    FrameArtifact,
    MediaFacts,
    PerceptionManifest,
    Rational,
    Shot,
    ShotDetectionResult,
)
from .pipeline import run_perception
from .probing import parse_ffprobe_json, probe_media
from .shots import detect_shots

__all__ = [
    "BoundaryEvaluation",
    "CutAnnotation",
    "DetectorConfig",
    "FFprobeUnavailableError",
    "FrameArtifact",
    "FrameExtractionError",
    "MediaFacts",
    "MediaFileNotFoundError",
    "NoVideoStreamError",
    "PerceptionError",
    "PerceptionManifest",
    "Rational",
    "SceneDetectorUnavailableError",
    "Shot",
    "ShotDetectionResult",
    "UnreadableMediaError",
    "detect_shots",
    "evaluate_boundaries",
    "extract_representative_frames",
    "parse_ffprobe_json",
    "probe_media",
    "run_perception",
]
