"""Explicit error/result categories for ingestion."""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for all ingestion failures."""

    category = "ingestion_error"

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail: dict = detail or {}

    def to_dict(self) -> dict:
        return {"category": self.category, "message": self.message, "detail": self.detail}


class InvalidURLError(IngestionError):
    category = "invalid_url"


class VideoUnavailableError(IngestionError):
    category = "video_unavailable"


class DownloadError_(IngestionError):
    category = "download_failure"


class MetadataParseError(IngestionError):
    category = "metadata_parse_failure"


class FileWriteError(IngestionError):
    category = "file_write_failure"


class CollectorUnavailableError(IngestionError):
    category = "collector_dependency_unavailable"


class ArtifactMismatchError(IngestionError):
    category = "artifact_mismatch"
