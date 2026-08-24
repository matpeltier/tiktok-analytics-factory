"""Collector adapters with an explicit fallback order.

Collectors return a :class:`CollectionResult`. On failure they raise an
:class:`~tiktok_analytics_factory.ingestion.errors.IngestionError`; the runner
records each failure so fallbacks are never silent.
"""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .errors import (
    CollectorUnavailableError,
    DownloadError_,
    IngestionError,
    MetadataParseError,
    VideoUnavailableError,
)
from .urls import canonical_url


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class CollectionResult:
    collector_name: str
    video_id: str
    source_url: str
    collected_at: str
    raw_payload: dict[str, Any]
    mp4_bytes: bytes | None = None  # None when the collector cannot fetch media
    creator_handle_hint: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Attempt:
    collector: str
    ok: bool
    error_category: str | None = None
    error_message: str | None = None


def _pkg_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


class PyktokCollector:
    """Preferred collector: uses the public pyktok library."""

    name = "pyktok"

    def __init__(self) -> None:
        self.version = _pkg_version("pyktok")

    def collect(self, url: str) -> CollectionResult:
        try:
            import pandas  # noqa: F401  (pyktok dependency check)
            import pyktok as pt
        except ImportError as exc:  # pragma: no cover - depends on env
            raise CollectorUnavailableError(
                "pyktok is not installed or its dependencies are missing.",
                detail={"dependency": str(exc)},
            ) from exc

        from tiktok_analytics_factory.ingestion.urls import extract_video_id

        collected_at = _utcnow()
        try:
            meta_rows = pt.tiktok_metadata(url, as_dict=True)
        except Exception as exc:
            raise VideoUnavailableError(
                f"pyktok could not retrieve metadata for {url}: {exc}",
                detail={"url": url},
            ) from exc
        if not meta_rows:
            raise MetadataParseError(f"pyktok returned no metadata for {url}.")
        payload: dict[str, Any] = dict(meta_rows)

        video_id_raw = payload.get("video_id") or payload.get("id")
        video_id = extract_video_id(str(video_id_raw)) if video_id_raw else None
        if video_id is None:
            raise MetadataParseError("pyktok metadata did not include a video ID.")

        handle = payload.get("author_unique_id") or payload.get("author")
        result = CollectionResult(
            collector_name=self.name,
            video_id=video_id,
            source_url=canonical_url(video_id),
            collected_at=collected_at,
            raw_payload=payload,
            creator_handle_hint=str(handle).lstrip("@") if handle else None,
        )

        try:
            import os
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                target = os.path.join(tmp, "video.mp4")
                pt.save_tiktok(url, True, target)
                if os.path.exists(target) and os.path.getsize(target) > 0:
                    with open(target, "rb") as fh:
                        result.mp4_bytes = fh.read()
                else:
                    raise DownloadError_(
                        "pyktok produced no MP4 file.",
                        detail={"url": url},
                    )
        except IngestionError:
            raise
        except Exception as exc:
            raise DownloadError_(
                f"pyktok failed to download the MP4 for {url}: {exc}",
                detail={"url": url},
            ) from exc
        return result


class YtDlpCollector:
    """Fallback collector: yt-dlp against the public page."""

    name = "yt-dlp"

    def __init__(self) -> None:
        self.version = _pkg_version("yt-dlp")

    def collect(self, url: str) -> CollectionResult:
        try:
            import yt_dlp
        except ImportError as exc:
            raise CollectorUnavailableError(
                "yt-dlp is not installed.", detail={"dependency": str(exc)}
            ) from exc

        from tiktok_analytics_factory.ingestion.urls import extract_video_id

        collected_at = _utcnow()
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            text = str(exc)
            if any(marker in text.lower() for marker in ("unavailable", "private", "removed", "not exist", "404")):
                raise VideoUnavailableError(
                    f"Video appears unavailable via yt-dlp: {text}",
                    detail={"url": url},
                ) from exc
            raise DownloadError_(
                f"yt-dlp failed for {url}: {text}", detail={"url": url}
            ) from exc
        except Exception as exc:
            raise IngestionError(f"Unexpected yt-dlp error: {exc}") from exc
        if not isinstance(info, dict):
            raise MetadataParseError("yt-dlp returned no parseable metadata.")

        vid = str(info.get("id") or extract_video_id(url))
        result = CollectionResult(
            collector_name=self.name,
            video_id=vid,
            source_url=info.get("webpage_url") or canonical_url(vid),
            collected_at=collected_at,
            raw_payload=info,
            creator_handle_hint=str(info.get("uploader") or "").lstrip("@") or None,
        )
        try:
            import os
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "noprogress": True,
                    "outtmpl": os.path.join(tmp, "video.%(ext)s"),
                    # Guarantee a real MP4 container: prefer native mp4, otherwise
                    # remux/merge into mp4 (requires ffmpeg; fails cleanly if
                    # remuxing is impossible).
                    "format": "best[ext=mp4]/best",
                    "merge_output_format": "mp4",
                    "remux_video_format": "mp4",
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.extract_info(url, download=True)
                files = [p for p in os.listdir(tmp) if p.startswith("video.")]
                if not files:
                    raise DownloadError_("yt-dlp downloaded no media file.")
                path = os.path.join(tmp, files[0])
                if not files[0].endswith(".mp4"):
                    raise DownloadError_(
                        f"yt-dlp produced a non-MP4 container ({files[0]}); "
                        "refusing to store it as video.mp4.",
                        detail={"file": files[0], "url": url},
                    )
                if os.path.getsize(path) > 0:
                    with open(path, "rb") as fh:
                        result.mp4_bytes = fh.read()
        except IngestionError:
            raise
        except Exception as exc:
            raise DownloadError_(
                f"yt-dlp could not fetch media bytes: {exc}", detail={"url": url}
            ) from exc
        if result.mp4_bytes is None:
            raise DownloadError_("No downloadable media URL found via yt-dlp.")
        return result


DEFAULT_COLLECTOR_ORDER: list[Any] = [PyktokCollector, YtDlpCollector]


def collect_with_fallback(url: str, order: list[Any] | None = None) -> tuple[CollectionResult, list[Attempt]]:
    """Try collectors in explicit order; record every failure.

    A collector counts as successful only when it returns a non-empty media
    artifact. A result without media bytes is recorded as a download failure
    and the next collector is attempted.
    """
    attempts: list[Attempt] = []
    classes = order if order is not None else DEFAULT_COLLECTOR_ORDER
    last_error: IngestionError | None = None
    for cls in classes:
        collector = cls()
        try:
            result = collector.collect(url)
        except CollectorUnavailableError as exc:
            attempts.append(Attempt(collector.name, False, exc.category, exc.message))
            last_error = exc
            continue
        except IngestionError as exc:
            attempts.append(Attempt(collector.name, False, exc.category, exc.message))
            last_error = exc
            continue
        if not result.mp4_bytes:
            missing = DownloadError_(
                f"Collector '{collector.name}' returned no media bytes.",
                detail={"collector": collector.name, "url": url},
            )
            attempts.append(Attempt(collector.name, False, missing.category, missing.message))
            last_error = missing
            continue
        attempts.append(Attempt(collector.name, True))
        return result, attempts
    raise last_error or IngestionError("All collectors failed.")
