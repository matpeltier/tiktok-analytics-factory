"""Explicit errors for the deterministic perception layer."""

from __future__ import annotations


class PerceptionError(Exception):
    """Base class for perception failures."""


class MediaFileNotFoundError(PerceptionError):
    pass


class UnreadableMediaError(PerceptionError):
    """Corrupt or otherwise undecodable media."""


class NoVideoStreamError(PerceptionError):
    pass


class FFprobeUnavailableError(PerceptionError):
    pass


class SceneDetectorUnavailableError(PerceptionError):
    pass


class FrameExtractionError(PerceptionError):
    pass
