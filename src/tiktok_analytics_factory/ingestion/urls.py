"""TikTok URL and video ID normalization."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .errors import InvalidURLError

TIKTOK_HOSTS = {"www.tiktok.com", "tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}
VIDEO_ID_RE = re.compile(r"^\d{6,32}$")
_PATH_VIDEO_RE = re.compile(r"^/video/(\d{6,32})")


def extract_video_id(url_or_id: str) -> str:
    """Extract a numeric TikTok video ID from a URL (including short links) or raw ID."""
    text = (url_or_id or "").strip()
    if not text:
        raise InvalidURLError("Empty URL or video ID.")
    if VIDEO_ID_RE.match(text):
        return text
    parsed = urlparse(text if "://" in text else f"https://{text}")
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in TIKTOK_HOSTS:
        raise InvalidURLError(f"Not a recognized TikTok URL: {url_or_id!r}", detail={"input": url_or_id})
    match = _PATH_VIDEO_RE.search(parsed.path)
    if match:
        return match.group(1)
    # Short-link form (vm.tiktok.com/xxxx) has no numeric ID; the ID is only
    # known after resolution, so we return the last path segment as a token.
    token = parsed.path.strip("/").split("/")[-1]
    if not token:
        raise InvalidURLError(
            f"Could not extract a video identifier from: {url_or_id!r}",
            detail={"input": url_or_id},
        )
    return token


def validate_tiktok_url(url: str) -> None:
    """Raise :class:`InvalidURLError` if ``url`` is not a TikTok URL."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in TIKTOK_HOSTS:
        raise InvalidURLError(f"Not a recognized TikTok URL: {url!r}", detail={"input": url})


def canonical_url(video_id: str) -> str:
    """Build the canonical tiktok.com URL for a numeric video ID."""
    if not VIDEO_ID_RE.match(video_id):
        raise InvalidURLError(f"Not a valid TikTok video ID: {video_id!r}")
    return f"https://www.tiktok.com/@tiktok/video/{video_id}"
