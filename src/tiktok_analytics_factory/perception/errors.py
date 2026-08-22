"""Explicit errors for the deterministic perception layer.

Rule: fail loudly. No silent fallbacks.
"""

from __future__ import annotations


class PerceptionError(Exception):
    """Base class for perception-layer failures."""


class VideoNotFoundError(PerceptionError):
    """The source video file does not exist."""


class FFprobeUnavailableError(PerceptionError):
    """The ffprobe binary is not installed or not executable."""


class CorruptMediaError(PerceptionError):
    """ffprobe/decoders cannot read the media (invalid or corrupt)."""


class NoVideoStreamError(PerceptionError):
    """The container has no video stream."""


class SceneDetectorUnavailableError(PerceptionError):
    """PySceneDetect is not importable."""


class FrameExtractionError(PerceptionError):
    """A representative frame could not be decoded for a shot."""
