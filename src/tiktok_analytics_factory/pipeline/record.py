"""Per-video record layout, record manifest, and rejection log."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RECORD_STATUSES = {
    "success",
    "rejected_by_cohort",
    "ingestion_failed",
    "perception_failed",
    "decompilation_failed",
    "validation_failed",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def build_record_dir(output_root: Path, video_id: str) -> Path:
    d = output_root / "records" / video_id
    for sub in ("source/performance", "perception/frames", "decompilation"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def _as_dict(r: Any) -> dict[str, Any]:
    if isinstance(r, dict):
        return r
    return {
        "usage_cost_usd": getattr(r, "usage_cost_usd", 0.0),
        "latency_seconds": getattr(r, "latency_seconds", 0.0),
        "prompt_version": getattr(r, "prompt_version", None),
        "model_id": getattr(r, "model_id", None),
        "schema_version": getattr(r, "schema_version", None),
    }


def build_manifest(
    *,
    entry: Any,
    cohort_id: str,
    cohort_version: str,
    status: str,
    stage_results: dict[str, Any],
    pipeline_version: str,
    source_hash: str | None,
    video_hash: str | None,
    failure: dict[str, str] | None = None,
    retry_policy: Any = None,
) -> dict[str, Any]:
    dicts = {k: _as_dict(v) for k, v in stage_results.items()}
    total_cost = sum(d.get("usage_cost_usd", 0.0) for d in dicts.values())
    total_latency = sum(d.get("latency_seconds", 0.0) for d in dicts.values())
    prompt_versions = {
        name: d["prompt_version"] for name, d in dicts.items() if d.get("prompt_version")
    }
    model_ids = {name: d["model_id"] for name, d in dicts.items() if d.get("model_id")}
    schema_versions = {name: d["schema_version"] for name, d in dicts.items() if d.get("schema_version")}
    manifest = {
        "video_id": entry.video_id,
        "source_url": entry.url,
        "cohort_id": cohort_id,
        "cohort_version": cohort_version,
        "status": status,
        "pipeline_version": pipeline_version,
        "prompt_versions": prompt_versions,
        "model_ids": model_ids,
        "schema_versions": schema_versions,
        "source_hash": source_hash,
        "video_hash": video_hash,
        "created_at": utc_now_iso(),
        "latency_seconds_by_stage": {
            k: v.get("latency_seconds", 0.0) for k, v in dicts.items()
        },
        "total_latency_seconds": round(total_latency, 6),
        "usage_cost_usd_by_stage": {
            k: v.get("usage_cost_usd", 0.0) for k, v in dicts.items()
        },
        "total_usage_cost_usd": round(total_cost, 6),
        "stages": {k: v.to_dict() if hasattr(v, "to_dict") else v for k, v in stage_results.items()},
    }
    if failure:
        manifest["failure"] = failure
    if retry_policy is not None:
        manifest["retry_policy"] = (
            retry_policy.to_dict() if hasattr(retry_policy, "to_dict") else retry_policy
        )
    return manifest


def persist_ingestion_failure(
    output_root: Path,
    entry: Any,
    video_id: str | None,
    category: str,
    message: str,
) -> None:
    """Append an auditable failed-attempt entry to failed_sources.jsonl.

    Used when a video fails before a record directory could be created
    (e.g. collection failed and no video ID was ever resolved).
    """
    out = output_root / "failed_sources.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "url": entry.url,
        "video_id": video_id,
        "status": "ingestion_failed",
        "failure_category": category,
        "message": message,
        "failed_at": utc_now_iso(),
    }
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def persist_rejection(
    output_root: Path,
    entry: Any,
    reason: str,
    cohort_id: str,
    cohort_version: str,
) -> None:
    """Append an auditable cohort-rejection entry to rejected_sources.jsonl."""
    out = output_root / "rejected_sources.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "url": entry.url,
        "video_id": entry.video_id,
        "reason": reason,
        "cohort_id": cohort_id,
        "cohort_version": cohort_version,
        "rejected_at": utc_now_iso(),
    }
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
