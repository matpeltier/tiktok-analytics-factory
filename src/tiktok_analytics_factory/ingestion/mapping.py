"""Mapping from collector payloads to the normalized metadata model."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .models import NormalizedMetadata


def _first(payload: dict, *paths: str) -> Any:
    for path in paths:
        cur: Any = payload
        found = True
        for key in path.split("."):
            if isinstance(cur, dict) and key in cur and cur[key] is not None:
                cur = cur[key]
            else:
                found = False
                break
        if found:
            return cur
    return None


def epoch_to_iso(value: Any) -> str | None:
    if value in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def normalize_payload(
    payload: dict[str, Any],
    *,
    video_id: str,
    source_url: str,
    collector_name: str,
    collected_at: str | None = None,
    collector_version: str | None = None,
    creator_handle_hint: str | None = None,
) -> NormalizedMetadata:
    """Map a raw collector payload (pyktok row dict or yt-dlp info dict) onto
    :class:`NormalizedMetadata`. Unknown values stay ``None``; never zero."""
    meta = NormalizedMetadata(
        platform="tiktok",
        video_id=video_id,
        source_url=source_url,
        collected_at=collected_at or datetime.now(UTC).isoformat(),
        collector_name=collector_name,
        collector_version=collector_version,
    )

    handle = (
        _first(payload, "author.unique_id", "uploader", "channel", "author")
        or creator_handle_hint
    )
    if isinstance(handle, str):
        meta.creator_handle = handle.lstrip("@") or None

    meta.creator_id = _str(_first(payload, "author.uid", "author_id", "uploader_id", "channel_id"))
    caption = _first(payload, "desc", "title", "description", "video_description")
    if isinstance(caption, str):
        meta.caption = caption

    hashtags = _first(payload, "text_extra", "hashtags")
    tags: list[str] = []
    if isinstance(hashtags, list):
        for item in hashtags:
            if isinstance(item, dict):
                name = item.get("hashtag_name") or item.get("name") or item.get("title")
            elif isinstance(item, str):
                name = item
            else:
                continue
            if name:
                tags.append(name.lstrip("#"))
    elif isinstance(caption, str):
        tags = [tok.lstrip("#") for tok in caption.split() if tok.startswith("#")]
    meta.hashtags = tags

    meta.published_at = (
        epoch_to_iso(_first(payload, "create_time", "timestamp", "release_timestamp"))
        or _str(_first(payload, "createTime", "upload_date_iso"))
    )

    duration = _first(payload, "video.duration", "duration")
    try:
        meta.duration_seconds = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        pass

    meta.views = _int(_first(payload, "stats.play_count", "play_count", "view_count", "views"))
    meta.likes = _int(_first(payload, "stats.digg_count", "digg_count", "like_count", "likes"))
    meta.comments = _int(_first(payload, "stats.comment_count", "comment_count", "comments"))
    meta.shares = _int(_first(payload, "stats.share_count", "share_count", "repost_count", "shares"))
    meta.saves = _int(
        _first(payload, "stats.collect_count", "collect_count", "save_count", "favorite_count")
    )
    meta.music_title = _str(
        _first(payload, "music.title", "music_meta.music_name", "track", "sound_track_name")
    )
    meta.music_author = _str(
        _first(payload, "music.author", "music_meta.music_author", "artist", "music_author")
    )
    return meta


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
