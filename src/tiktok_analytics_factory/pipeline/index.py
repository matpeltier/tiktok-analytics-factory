"""Parquet dataset index: one row per video record."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

INDEX_SCHEMA = pa.schema(
    [
        ("video_id", pa.string()),
        ("creator_id", pa.string()),
        ("creator_handle", pa.string()),
        ("source_url", pa.string()),
        ("cohort_id", pa.string()),
        ("published_at", pa.string()),
        ("observed_at", pa.string()),
        ("views", pa.int64()),
        ("likes", pa.int64()),
        ("comments", pa.int64()),
        ("shares", pa.int64()),
        ("duration_seconds", pa.float64()),
        ("status", pa.string()),
        ("creative_ir_path", pa.string()),
        ("canonical_ir_path", pa.string()),
        ("pipeline_version", pa.string()),
        ("schema_versions", pa.string()),  # JSON map
        ("model_ids", pa.string()),  # JSON map
        ("total_usage_cost_usd", pa.float64()),
        ("total_latency_seconds", pa.float64()),
    ]
)


def _row_from_manifest(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    src = manifest.get("source", {})
    perf = manifest.get("performance_snapshot_observed", {})
    return {
        "video_id": manifest.get("video_id"),
        "creator_id": src.get("creator_id"),
        "creator_handle": src.get("creator_handle"),
        "source_url": manifest.get("source_url"),
        "cohort_id": manifest.get("cohort_id"),
        "published_at": src.get("published_at"),
        "observed_at": perf.get("observed_at"),
        "views": perf.get("views"),
        "likes": perf.get("likes"),
        "comments": perf.get("comments"),
        "shares": perf.get("shares"),
        "duration_seconds": src.get("duration_seconds"),
        "status": manifest.get("status"),
        "creative_ir_path": manifest.get("creative_ir_path"),
        "canonical_ir_path": manifest.get("canonical_ir_path"),
        "pipeline_version": manifest.get("pipeline_version"),
        "schema_versions": json_dumps(manifest.get("schema_versions") or {}),
        "model_ids": json_dumps(manifest.get("model_ids") or {}),
        "total_usage_cost_usd": manifest.get("total_usage_cost_usd", 0.0),
        "total_latency_seconds": manifest.get("total_latency_seconds", 0.0),
    }


def json_dumps(v: Any) -> str:
    import json

    return json.dumps(v, sort_keys=True)


def build_index(records_root: Path, index_path: Path) -> list[dict[str, Any]]:
    """Scan record manifests and write the Parquet index. Returns the rows."""
    rows: list[dict[str, Any]] = []
    for manifest_path in sorted(Path(records_root).glob("*/record_manifest.json")):
        import json

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows.append(_row_from_manifest(manifest_path.parent, manifest))
    if rows:
        table = pa.Table.from_pylist(rows, schema=INDEX_SCHEMA)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, index_path)
    return rows
