"""Normalized metadata model for ingested TikTok videos.

Convention: unknown/unavailable values are ``None`` (rendered as JSON
``null``). Zero is never used to mean unknown.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class NormalizedMetadata:
    platform: str = "tiktok"
    video_id: str | None = None
    source_url: str | None = None
    creator_handle: str | None = None
    creator_id: str | None = None
    caption: str | None = None
    hashtags: list[str] = field(default_factory=list)
    published_at: str | None = None  # ISO-8601 UTC when derivable
    duration_seconds: float | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    music_title: str | None = None
    music_author: str | None = None
    collected_at: str | None = None  # ISO-8601 UTC
    collector_name: str | None = None
    collector_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None} or {"platform": self.platform}

    def to_json_dict(self) -> dict[str, Any]:
        """Full record with explicit nulls for unknown values."""
        return asdict(self)
