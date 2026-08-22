"""Single-video ingestion pipeline: download, persist, and record provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from importlib.metadata import version as _pkg_version
    PACKAGE_VERSION = _pkg_version("tiktok-analytics-factory")
except Exception:  # pragma: no cover
    PACKAGE_VERSION = "0.0.0"

from .collectors import Attempt, CollectionResult, collect_with_fallback
from .errors import ArtifactMismatchError, FileWriteError, InvalidURLError
from .mapping import normalize_payload
from .models import NormalizedMetadata
from .urls import extract_video_id, canonical_url, validate_tiktok_url


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        raise FileWriteError(f"Could not write {path}: {exc}") from exc


class IngestionResult:
    def __init__(
        self,
        *,
        video_id: str,
        artifact_dir: Path,
        metadata: NormalizedMetadata,
        manifest: dict,
        reused_existing_mp4: bool,
        attempts: list[Attempt],
    ) -> None:
        self.video_id = video_id
        self.artifact_dir = artifact_dir
        self.metadata = metadata
        self.manifest = manifest
        self.reused_existing_mp4 = reused_existing_mp4
        self.attempts = attempts


def ingest(
    url: str,
    output_root: str | Path = "data/raw",
    *,
    force_new_observation: bool = False,
) -> IngestionResult:
    """Ingest one public TikTok URL into ``<output_root>/<video_id>/``.

    Idempotency rules:
      - an existing MP4 is never silently overwritten;
      - if a new download hashes differently from the stored MP4, raise;
      - if it matches, the MP4 is reused;
      - metadata snapshots are versioned by timestamp when a new observation
        is forced (engagement counts change over time).
    """
    if not url or not str(url).strip():
        raise InvalidURLError("A TikTok URL is required.")
    url = str(url).strip()
    validate_tiktok_url(url)

    result, attempts = collect_with_fallback(url)
    video_id = result.video_id

    artifact_dir = Path(output_root) / video_id
    mp4_path = artifact_dir / "video.mp4"
    raw_meta_path = artifact_dir / "metadata.raw.json"
    norm_meta_path = artifact_dir / "metadata.normalized.json"
    manifest_path = artifact_dir / "manifest.json"

    new_hash = sha256_of(result.mp4_bytes) if result.mp4_bytes else None
    reused = False

    if mp4_path.exists():
        existing_hash = sha256_of(mp4_path.read_bytes())
        if new_hash is not None and existing_hash != new_hash:
            raise ArtifactMismatchError(
                f"Downloaded MP4 for video {video_id} differs from the stored artifact; "
                "refusing to overwrite.",
                detail={
                    "video_id": video_id,
                    "existing_sha256": existing_hash,
                    "downloaded_sha256": new_hash,
                    "path": str(mp4_path),
                },
            )
        reused = True
        file_hash, size = existing_hash, mp4_path.stat().st_size
    elif new_hash is not None:
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            mp4_path.write_bytes(result.mp4_bytes)
        except OSError as exc:
            raise FileWriteError(f"Could not write {mp4_path}: {exc}") from exc
        file_hash, size = new_hash, len(result.mp4_bytes)
    else:
        file_hash, size = None, 0

    collected_at = result.collected_at
    metadata = normalize_payload(
        result.raw_payload,
        video_id=video_id,
        source_url=result.source_url,
        collector_name=result.collector_name,
        collected_at=collected_at,
        collector_version=_collector_version(result),
        creator_handle_hint=result.creator_handle_hint,
    )

    if raw_meta_path.exists() and not force_new_observation:
        pass  # keep original raw snapshot immutable
    elif force_new_observation and raw_meta_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        versioned = artifact_dir / f"metadata.raw.{stamp}.json"
        _write_json(versioned, result.raw_payload)
        _write_json(artifact_dir / f"metadata.normalized.{stamp}.json", metadata.to_json_dict())
    else:
        _write_json(raw_meta_path, result.raw_payload)

    if not norm_meta_path.exists():
        _write_json(norm_meta_path, metadata.to_json_dict())

    rel = lambda name: (artifact_dir / name).as_posix()  # noqa: E731
    manifest_artifacts = {
        "video": rel("video.mp4"),
        "metadata_raw": rel("metadata.raw.json"),
        "metadata_normalized": rel("metadata.normalized.json"),
        "manifest": rel("manifest.json"),
    }
    if not manifest_path.exists():
        _write_json(manifest_path, {})

    fallback_notes = [
        {"collector": a.collector, "error_category": a.error_category, "message": a.error_message}
        for a in attempts
        if not a.ok
    ]
    manifest = {
        "source_url": url,
        "canonical_source_url": canonical_url(video_id),
        "video_id": video_id,
        "artifacts": manifest_artifacts,
        "sha256": file_hash,
        "byte_size": size,
        "mp4_reused_from_previous_run": reused,
        "collected_at": collected_at,
        "collector_name": result.collector_name,
        "collector_version": _collector_version(result),
        "attempted_collectors_in_order": [a.collector for a in attempts],
        "attempts": [asdict(a) for a in attempts],
        "fallback_or_error_notes": fallback_notes,
        "package_version": PACKAGE_VERSION,
    }
    _write_json(manifest_path, manifest)

    return IngestionResult(
        video_id=video_id,
        artifact_dir=artifact_dir,
        metadata=metadata,
        manifest=manifest,
        reused_existing_mp4=reused,
        attempts=attempts,
    )


def _collector_version(result: CollectionResult) -> str | None:
    from .collectors import PyktokCollector, YtDlpCollector

    if isinstance(result.collector_name, str):
        for cls in (PyktokCollector, YtDlpCollector):
            if cls.name == result.collector_name:
                return cls().version
    return None
