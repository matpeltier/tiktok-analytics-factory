"""Generate a synthetic-but-schema-faithful pilot snapshot set for target design.

The issue #8 pilot snapshots were not present in this worktree, so this script
produces a small stand-in set that uses EXACTLY the field names and semantics of
``NormalizedMetadata`` (issue #3). It exists only to exercise and demonstrate
the target pipeline; it must be replaced by real pilot snapshots as soon as they
are available. Output goes under ``data/pilot/snapshots/`` using the ingestion
layout (``<video_id>/metadata.normalized.json``).
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

OUT_ROOT = Path("data/pilot/snapshots")

CREATORS = {
    "cr_sourdough": ("sourdough.sci", [12000, 45000, 30000, 80000]),
    "cr_laminated": ("laminated.lab", [900000, 1500000, 700000]),
    "cr_focaccia": ("focaccia.friday", [5000, 9000, 4200, 7800, 6100, 3300]),
    "cr_bagel": ("boil.then.bake", [250000, 90, 310000]),
    "cr_ciabatta": ("ciabatta.quiet", [1400, 21000, None]),
}

BASE_DATE = datetime(2026, 8, 20, tzinfo=UTC)
OBSERVED_AT = "2026-08-24T12:00:00+00:00"


def main() -> int:
    rng = random.Random(42)
    n = 0
    for creator_key, (handle, view_list) in CREATORS.items():
        for i, views in enumerate(view_list):
            n += 1
            video_id = f"73{n:018d}"
            likes = int(views * rng.uniform(0.05, 0.14)) if views else None
            comments = int(views * rng.uniform(0.002, 0.01)) if views else None
            shares = int(views * rng.uniform(0.001, 0.02)) if views else None
            age_days = rng.choice([1.5, 3.0, 7.2, 30.4, 120.0])
            published = BASE_DATE - timedelta(days=age_days)
            payload = {
                "platform": "tiktok",
                "video_id": video_id,
                "source_url": f"https://www.tiktok.com/@{handle}/video/{video_id}",
                "creator_handle": handle,
                "creator_id": creator_key,
                "caption": f"pilot bread clip {i}",
                "hashtags": ["baking"],
                "published_at": published.isoformat(),
                "duration_seconds": round(rng.uniform(8, 45), 1),
                "views": views,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "saves": None,
                "music_title": None,
                "music_author": None,
                "collected_at": OBSERVED_AT,
                "collector_name": "synthetic-pilot",
                "collector_version": "0.1",
            }
            d = OUT_ROOT / video_id
            d.mkdir(parents=True, exist_ok=True)
            (d / "metadata.normalized.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )

    # one deliberately broken record: missing creator identity AND views
    bad = dict(payload)
    bad.update({
        "video_id": "73999999999999999999",
        "creator_handle": None,
        "creator_id": None,
        "views": None,
        "likes": None,
        "comments": None,
        "shares": None,
        "published_at": None,
    })
    d = OUT_ROOT / bad["video_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "metadata.normalized.json").write_text(json.dumps(bad, indent=2), encoding="utf-8")
    print(f"wrote {n + 1} pilot snapshots under {OUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
