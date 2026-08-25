"""Builders for synthetic dataset records used by the QA test-suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOOD_MANIFEST = {
    "video_id": "7300000000000000001",
    "source_url": "https://www.tiktok.com/@bakerylab/video/7300000000000000001",
    "creator": "bakerylab",
    "published_at": "2026-01-01T00:00:00+00:00",
    "observed_at": "2026-02-01T00:00:00+00:00",
    "mp4_path": None,  # filled by builder (absolute)
    "mp4_sha256": "a" * 64,
    "cohort_id": "sourdough-v1",
    "cohort_version": "1.0.0",
    "status": "success",
    "pipeline_version": "0.1.0",
    "schema_version": "0.1.0",
    "prompt_version": "p1",
    "model_id": "test-model",
    "cost_usd": 0.42,
    "latency_s": 31.5,
}

def good_perception() -> dict[str, Any]:
    return {
        "media": {"duration_s": 10.0, "width": 1080, "height": 1920, "fps": 30.0},
        "shots": [
            {
                "shot_id": "shot_001",
                "start_s": 0.0,
                "end_s": 10.0,
                "representative_frame": "frames/shot_001.jpg",
            }
        ],
    }


def good_creative_ir() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "pipeline_version": "0.1.0",
        "prompt_version": "p1",
        "model_id": "test-model",
        "source_video_id": "7300000000000000001",
        "shots": [
            {
                "shot_id": "shot_001",
                "time_range": {"start_s": 0.0, "end_s": 10.0},
                "text_overlays": [{"text_id": "txt_001", "text": "day 1 of sourdough"}],
                "spoken_dialogue": [],
                "visual_description": {
                    "label": "kneading",
                    "inferred_from": [{"id": "shot_001"}],
                },
            }
        ],
    }


def good_performance() -> dict[str, Any]:
    return {
        "snapshots": [
            {
                "observed_at": "2026-02-01T00:00:00+00:00",
                "metrics": {"views": 15234, "likes": 812, "shares": 7, "comments": 43},
            }
        ]
    }


def build_record(
    root: Path,
    video_id: str = "7300000000000000001",
    *,
    manifest: dict[str, Any] | None = None,
    perception: dict[str, Any] | None = None,
    creative_ir: dict[str, Any] | None = None,
    canonical_ir: dict[str, Any] | None = None,
    performance: dict[str, Any] | None = None,
) -> Path:
    from tiktok_analytics_factory.qa.projection import project_canonical

    rec_dir = root / video_id
    rec_dir.mkdir(parents=True, exist_ok=True)
    (rec_dir / "frames").mkdir(exist_ok=True)
    frame = rec_dir / "frames" / "shot_001.jpg"
    if not frame.exists():
        frame.write_bytes(b"\xff\xd8fakejpeg")

    m = dict(GOOD_MANIFEST)
    m["mp4_path"] = str(rec_dir / "source.mp4")
    (rec_dir / "source.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    if manifest:
        m.update(manifest)
        for key, val in list(m.items()):
            if val is Ellipsis:
                del m[key]
    if "video_id" not in (manifest or {}):
        m["video_id"] = video_id

    parts: dict[str, dict[str, Any]] = {
        "perception": dict(good_perception()) if perception is None else perception,
        "creative_ir": None,
        "canonical_ir": None,
        "performance": good_performance() if performance is None else performance,
    }
    if creative_ir is None:
        ir = good_creative_ir()
        ir["source_video_id"] = video_id
        parts["creative_ir"] = ir
    elif creative_ir is Ellipsis:
        parts["creative_ir"] = None
    else:
        parts["creative_ir"] = creative_ir
    if parts["performance"] is Ellipsis:
        parts["performance"] = None

    if canonical_ir is Ellipsis:
        parts["canonical_ir"] = None
    elif isinstance(canonical_ir, dict):
        parts["canonical_ir"] = canonical_ir
    else:
        proj = project_canonical(parts["creative_ir"])
        parts["canonical_ir"] = (
            {"schema_version": "0.1.0", "source_video_id": video_id, "projection": proj}
            if proj is not None
            else None
        )

    with open(rec_dir / "record.json", "w", encoding="utf-8") as fh:
        json.dump(m, fh)
    for name in ("perception", "creative_ir", "canonical_ir", "performance"):
        if parts[name] is not None:
            with open(rec_dir / f"{name}.json", "w", encoding="utf-8") as fh:
                json.dump(parts[name], fh)
    return rec_dir


def write_cohort_config(dataset_root: Path) -> Path:
    path = dataset_root.parent / "cohort.json"
    path.write_text(
        json.dumps({"cohort_id": "sourdough-v1", "cohort_version": "1.0.0"}), encoding="utf-8"
    )
    return path
