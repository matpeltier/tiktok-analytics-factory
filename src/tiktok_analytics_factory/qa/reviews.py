"""Human review persistence model.

Reviews are stored as machine-readable JSON:

    data/reviews/<video_id>/<review_id>.json

A review is versioned against the reviewed record via the sha256 of the
record manifest at review time.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .records import DatasetRecord, canonical_json
from .taxonomy import TAXONOMY_VERSION, ReviewError, utcnow_iso

REVIEW_FORMAT_VERSION = "1.0.0"

# Quality scorecard categories (reused from issues #4/#6 quality dimensions).
SCORECARD_CATEGORIES: tuple[str, ...] = (
    "shot_timeline",
    "ocr_text",
    "dialogue",
    "visual_description",
    "camera_editing",
    "audio",
    "hook",
    "narrative",
    "commercial_reasoning",
    "reconstruction",
)


@dataclass
class Review:
    video_id: str
    reviewer: str
    scores: dict[str, int] = field(default_factory=dict)
    errors: list[ReviewError] = field(default_factory=list)
    notes: str = ""
    review_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(default_factory=utcnow_iso)
    source_record_hash: str | None = None
    format_version: str = REVIEW_FORMAT_VERSION

    def __post_init__(self) -> None:
        for cat, score in self.scores.items():
            if cat not in SCORECARD_CATEGORIES:
                raise ValueError(f"unknown scorecard category: {cat!r}")
            if not isinstance(score, int) or not 1 <= score <= 5:
                raise ValueError(f"score for {cat!r} must be an int in 1..5, got {score!r}")

    def validation_problems(self) -> list[str]:
        problems: list[str] = []
        for cat, score in self.scores.items():
            if score <= 2 and not (self.notes.strip() or any(e.note for e in self.errors)):
                problems.append(
                    f"a note is required when a score <= 2 (category {cat!r})"
                )
                break
        if any(e.severity == "blocking" for e in self.errors) and not (
            self.notes.strip() or all(e.note for e in self.errors if e.severity == "blocking")
        ):
            problems.append("a note is required when severity is 'blocking'")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "taxonomy_version": TAXONOMY_VERSION,
            "review_id": self.review_id,
            "video_id": self.video_id,
            "reviewer": self.reviewer,
            "timestamp": self.timestamp,
            "source_record_hash": self.source_record_hash,
            "scores": dict(sorted(self.scores.items())),
            "errors": [e.to_dict() for e in self.errors],
            "notes": self.notes,
        }

    def save(self, reviews_root: Path) -> Path:
        if not self.reviewer:
            raise ValueError("reviewer name is required")
        problems = self.validation_problems()
        if problems:
            raise ValueError("; ".join(problems))
        out_dir = Path(reviews_root) / self.video_id
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{self.review_id}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        return path


def review_for_record(record: DatasetRecord, **kwargs: Any) -> Review:
    """Create a review pinned to the current record manifest hash."""
    kwargs.setdefault("video_id", record.video_id)
    review = Review(source_record_hash=record.record_hash(), **kwargs)
    return review


def load_review(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def list_reviews(reviews_root: Path, video_id: str | None = None) -> list[Path]:
    root = Path(reviews_root)
    if not root.is_dir():
        return []
    dirs = [root / video_id] if video_id else sorted(p for p in root.iterdir() if p.is_dir())
    paths: list[Path] = []
    for d in dirs:
        if d.is_dir():
            paths.extend(sorted(d.glob("*.json")))
    return paths


def is_review_current(review: dict[str, Any], record: DatasetRecord) -> bool:
    return review.get("source_record_hash") == record.record_hash()


def aggregate_reviews(reviews_root: Path) -> dict[str, Any]:
    """Aggregate human error counts/severity by category across all reviews."""
    by_category: dict[str, dict[str, int]] = {}
    total = 0
    for path in list_reviews(Path(reviews_root)):
        data = load_review(path)
        total += 1
        for err in data.get("errors", []):
            cat = err.get("category", "other")
            sev = err.get("severity", "minor")
            slot = by_category.setdefault(cat, {"minor": 0, "material": 0, "blocking": 0})
            slot[sev] = slot.get(sev, 0) + 1
    return {"reviewed_count": total, "errors_by_category": dict(sorted(by_category.items()))}


def review_sort_key(data: dict[str, Any]) -> str:
    return canonical_json(
        {"v": data.get("video_id"), "t": data.get("timestamp"), "id": data.get("review_id")}
    )
