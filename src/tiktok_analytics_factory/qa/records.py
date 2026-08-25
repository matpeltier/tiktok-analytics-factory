"""Dataset record model and on-disk layout for the pilot dataset.

Layout (documented contract for the QA layer):

    data/dataset/<video_id>/
        record.json        # manifest: provenance, paths, versions, status
        perception.json    # deterministic media facts + shots
        creative_ir.json   # CreativeIR document
        canonical_ir.json  # CanonicalIR projection of CreativeIR
        performance.json   # Performance v0.1 snapshot(s)

All timestamps are ISO-8601 strings with timezone offset.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RECORD_FILENAME = "record.json"


def canonical_json(obj: Any) -> str:
    """Documented canonical serialization rule (used for projection comparison)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_record(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest()


@dataclass
class DatasetRecord:
    """A fully loaded record from the dataset directory."""

    video_id: str
    root: Path
    manifest: dict[str, Any]
    perception: dict[str, Any] | None = None
    creative_ir: dict[str, Any] | None = None
    canonical_ir: dict[str, Any] | None = None
    performance: dict[str, Any] | None = None

    @property
    def status(self) -> str:
        return str(self.manifest.get("status", "unknown"))

    @property
    def creator(self) -> str | None:
        creator = self.manifest.get("creator")
        if isinstance(creator, dict):
            return creator.get("handle")
        return creator

    def source_hash(self) -> str | None:
        return self.manifest.get("mp4_sha256")

    def record_hash(self) -> str:
        return hash_record(self.manifest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "manifest": self.manifest,
            "perception": self.perception,
            "creative_ir": self.creative_ir,
            "canonical_ir": self.canonical_ir,
            "performance": self.performance,
        }


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_record(dataset_root: Path, video_id: str) -> DatasetRecord:
    rec_root = Path(dataset_root) / video_id
    manifest = _load_json(rec_root / RECORD_FILENAME)
    rec = DatasetRecord(video_id=video_id, root=rec_root, manifest=manifest)
    for name in ("perception", "creative_ir", "canonical_ir", "performance"):
        path = rec_root / f"{name}.json"
        if path.exists():
            setattr(rec, name, _load_json(path))
    return rec


def list_video_ids(dataset_root: Path) -> list[str]:
    root = Path(dataset_root)
    if not root.is_dir():
        raise FileNotFoundError(f"dataset root does not exist: {root}")
    ids = [
        p.name
        for p in sorted(root.iterdir())
        if p.is_dir() and (p / RECORD_FILENAME).is_file()
    ]
    return ids


def load_all_records(dataset_root: Path) -> list[DatasetRecord]:
    return [load_record(Path(dataset_root), vid) for vid in list_video_ids(dataset_root)]
