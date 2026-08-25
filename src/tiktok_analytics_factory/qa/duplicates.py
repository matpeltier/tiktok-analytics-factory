"""Exact duplicate detection (video IDs and source hashes).

Sophisticated perceptual near-duplicate detection is intentionally out of
scope; a ``duplicate`` flag field is reserved on findings for future use.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .records import DatasetRecord, load_all_records


@dataclass
class DuplicateGroup:
    kind: str  # "video_id" or "source_hash"
    key: str
    video_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "key": self.key, "video_ids": self.video_ids}


def find_duplicates(records: list[DatasetRecord]) -> dict[str, list[DuplicateGroup]]:
    by_video_id: dict[str, list[str]] = defaultdict(list)
    by_hash: dict[str, list[str]] = defaultdict(list)
    for rec in records:
        by_video_id[rec.video_id].append(rec.video_id)
        # manifest video_id is the authoritative source id; a mismatch with the
        # directory name means two records claim the same source video.
        manifest_vid = rec.manifest.get("video_id")
        if manifest_vid:
            by_video_id[str(manifest_vid)].append(f"{rec.video_id}#manifest")
        h = rec.source_hash()
        if h:
            by_hash[str(h)].append(rec.video_id)

    dup_ids = [
        DuplicateGroup("video_id", k, v) for k, v in sorted(by_video_id.items()) if len(v) > 1
    ]
    dup_hashes = [
        DuplicateGroup("source_hash", k, sorted(v)) for k, v in sorted(by_hash.items()) if len(v) > 1
    ]
    return {"video_id": dup_ids, "source_hash": dup_hashes}


def find_duplicates_in_dataset(dataset_root: Path) -> dict[str, list[DuplicateGroup]]:
    return find_duplicates(load_all_records(Path(dataset_root)))
