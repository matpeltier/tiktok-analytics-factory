"""Explicit, versionable pilot source lists (CSV or JSONL)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REQUIRED_COLUMNS = ("url",)


@dataclass(frozen=True)
class SourceEntry:
    """One candidate source row from the explicit pilot source list."""

    url: str
    video_id: str | None = None
    creator_handle: str | None = None
    hashtags: list[str] = field(default_factory=list)
    views: int | None = None
    published_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "video_id": self.video_id,
            "creator_handle": self.creator_handle,
            "hashtags": self.hashtags,
            "views": self.views,
            "published_at": self.published_at,
            **self.extra,
        }


def _make_entry(row: dict[str, Any], line_no: int) -> SourceEntry:
    missing = [c for c in _REQUIRED_COLUMNS if not row.get(c)]
    if missing:
        raise ValueError(f"source row {line_no}: missing required field(s) {missing}")
    known = {"url", "video_id", "creator_handle", "hashtags", "views", "published_at"}
    extra = {k: v for k, v in row.items() if k not in known}
    hashtags_raw = row.get("hashtags")
    if isinstance(hashtags_raw, str):
        hashtags = [t.strip().lstrip("#") for t in hashtags_raw.split(";") if t.strip()]
    elif isinstance(hashtags_raw, list):
        hashtags = [str(t).lstrip("#") for t in hashtags_raw]
    else:
        hashtags = []
    return SourceEntry(
        url=str(row["url"]).strip(),
        video_id=row.get("video_id") or None,
        creator_handle=row.get("creator_handle") or None,
        hashtags=hashtags,
        views=int(row["views"]) if row.get("views") not in (None, "") else None,
        published_at=row.get("published_at") or None,
        extra=extra,
    )


def load_sources(path: str | Path) -> list[SourceEntry]:
    """Load the explicit source list. Supported: ``.csv`` and ``.jsonl``."""
    p = Path(path)
    suffix = p.suffix.lower()
    entries: list[SourceEntry] = []
    if suffix == ".csv":
        with p.open(newline="", encoding="utf-8") as fh:
            for i, row in enumerate(csv.DictReader(fh), start=2):
                entries.append(_make_entry({k: v for k, v in row.items()}, i))
    elif suffix == ".jsonl":
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            entries.append(_make_entry(json.loads(line), i))
    else:
        raise ValueError(f"unsupported source list format: {suffix} (use .csv or .jsonl)")
    if not entries:
        raise ValueError(f"source list is empty: {p}")
    urls = [e.url for e in entries]
    dupes = sorted({u for u in urls if urls.count(u) > 1})
    if dupes:
        raise ValueError(f"duplicate source URLs: {dupes}")
    return entries
