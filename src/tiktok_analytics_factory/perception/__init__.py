"""Deterministic perception layer: media probing, shot segmentation,
representative frames. No model/VLM/OCR dependency by design."""

from .models import (
    PIPELINE_VERSION,
    FrameArtifact,
    MediaFacts,
    PerceptionConfig,
    PerceptionManifest,
    Shot,
    ShotDetectionResult,
)
from .probe import probe_media, sha256_file
from .shots import detect_shots
from .frames import extract_representative_frames
from .pipeline import run_perception
from .evaluation import BoundaryEvaluation, evaluate_boundaries

__all__ = [
    "PIPELINE_VERSION",
    "FrameArtifact",
    "MediaFacts",
    "PerceptionConfig",
    "PerceptionManifest",
    "Shot",
    "ShotDetectionResult",
    "probe_media",
    "sha256_file",
    "detect_shots",
    "extract_representative_frames",
    "run_perception",
    "BoundaryEvaluation",
    "evaluate_boundaries",
]
