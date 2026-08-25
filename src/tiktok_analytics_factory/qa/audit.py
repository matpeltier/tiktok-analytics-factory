"""Dataset-level audit: aggregate automatic validation and human review data
into a single machine-readable JSON report. No model or network calls.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .duplicates import find_duplicates
from .records import DatasetRecord, canonical_json, load_all_records
from .reviews import REVIEW_FORMAT_VERSION, aggregate_reviews, list_reviews, load_review
from .taxonomy import TAXONOMY_VERSION
from .validators import run_validators

AUDIT_FORMAT_VERSION = "1.0.0"

IMPORTANT_METADATA_FIELDS = (
    "video_id",
    "source_url",
    "creator",
    "published_at",
    "observed_at",
    "mp4_sha256",
    "mp4_path",
    "cohort_id",
    "pipeline_version",
    "schema_version",
    "model_id",
    "prompt_version",
)


def _percent(numer: int, denom: int) -> float | None:
    return round(100.0 * numer / denom, 2) if denom else None


def _distribution(values: Iterable[Any]) -> dict[str, int]:
    return dict(sorted(Counter(str(v) for v in values).items()))


def _numeric_summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "n": len(values),
        "min": round(min(values), 6),
        "median": round(statistics.median(values), 6),
        "mean": round(statistics.fmean(values), 6),
        "max": round(max(values), 6),
    }


def _creator_concentration(records: list[DatasetRecord]) -> dict[str, Any]:
    counts = Counter(rec.creator or "<unknown>" for rec in records)
    total = sum(counts.values())
    top = counts.most_common()
    return {
        "counts": dict(sorted(counts.items())),
        "top_creator_share_pct": _percent(top[0][1], total) if top else None,
        "distinct_creators": len(counts),
    }


def _cost_latency(records: list[DatasetRecord]) -> dict[str, Any]:
    costs: list[float] = []
    latencies: list[float] = []
    for rec in records:
        for key, bucket in (("cost_usd", costs), ("latency_s", latencies)):
            val = rec.manifest.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                bucket.append(float(val))
            elif isinstance(val, list):
                bucket.extend(float(v) for v in val if isinstance(v, (int, float)) and not isinstance(v, bool))
    return {"cost_usd": _numeric_summary(costs), "latency_s": _numeric_summary(latencies)}


def audit_record(record: DatasetRecord) -> dict[str, Any]:
    issues = run_validators(record)
    return {
        "video_id": record.video_id,
        "status": record.status,
        "passed": not issues,
        "issues": [i.to_dict() for i in issues],
        "parts_present": {
            name: getattr(record, name) is not None
            for name in ("perception", "creative_ir", "canonical_ir", "performance")
        },
    }


def audit_dataset(
    dataset_root: Path,
    reviews_root: Path | None = None,
) -> dict[str, Any]:
    dataset_root = Path(dataset_root)
    records = load_all_records(dataset_root)
    per_record = [audit_record(rec) for rec in records]

    status_counts = Counter(r["status"] for r in per_record)
    passed = sum(1 for r in per_record if r["passed"])
    issue_counts = Counter(i["category"] for r in per_record for i in r["issues"])

    # Missing metadata rates
    missing: dict[str, int] = {}
    for rec in records:
        for field in IMPORTANT_METADATA_FIELDS:
            value = rec.manifest.get(field)
            empty = value is None or value == "" or value == [] or value == {}
            if field == "creator":
                empty = rec.creator is None
            if empty:
                missing[field] = missing.get(field, 0) + 1

    # Schema validation rates: part present AND no schema-level issue categories
    schema_cats = {"schema_validation", "canonical_projection"}
    schema_rates: dict[str, Any] = {}
    for part, cat_key in (
        ("creative_ir", "schema_validation"),
        ("canonical_ir", "canonical_projection"),
        ("performance", "performance_snapshot"),
        ("perception", "media_probe"),
    ):
        present = sum(1 for rec in records if getattr(rec, part) is not None)
        clean = sum(
            1
            for rec, res in zip(records, per_record)
            if getattr(rec, part) is not None
            and not any(i["category"] in schema_cats and cat_key == i["category"] for i in res["issues"])
        )
        schema_rates[part] = {
            "present": present,
            "valid": clean,
            "valid_rate_pct": _percent(clean, present),
        }

    projection_mismatches = sum(
        1
        for r in per_record
        for i in r["issues"]
        if i["category"] == "canonical_projection" and "projection" in i["message"]
    )

    duplicates = find_duplicates(records)

    versions = {
        "pipeline_version": _distribution(rec.manifest.get("pipeline_version") for rec in records),
        "schema_version": _distribution(rec.manifest.get("schema_version") for rec in records),
        "prompt_version": _distribution(rec.manifest.get("prompt_version") for rec in records),
        "model_id": _distribution(
            rec.creative_ir.get("model_id") if rec.creative_ir else rec.manifest.get("model_id")
            for rec in records
        ),
    }

    review_summary: dict[str, Any] = {"reviewed_count": 0, "errors_by_category": {}}
    reviewed_ids: set[str] = set()
    if reviews_root is not None and Path(reviews_root).is_dir():
        review_summary.update(aggregate_reviews(Path(reviews_root)))
        for path in list_reviews(Path(reviews_root)):
            data = load_review(path)
            reviewed_ids.add(data.get("video_id", ""))
            fmt = data.get("format_version")
            if fmt != REVIEW_FORMAT_VERSION:
                review_summary.setdefault("review_format_mismatches", []).append(
                    {"path": str(path), "format_version": fmt}
                )

    report = {
        "format_version": AUDIT_FORMAT_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "dataset_root": str(dataset_root),
        "total_records": len(records),
        "status_counts": dict(sorted(status_counts.items())),
        "validation": {
            "pass_rate_pct": _percent(passed, len(records)),
            "records_passed": passed,
            "issue_count_by_category": dict(sorted(issue_counts.items())),
            "per_record": per_record,
        },
        "missing_metadata_rates": {
            field: {"missing": missing.get(field, 0), "rate_pct": _percent(missing.get(field, 0), len(records))}
            for field in IMPORTANT_METADATA_FIELDS
        },
        "schema_validation_rates": schema_rates,
        "canonical_projection_mismatch_count": projection_mismatches,
        "duplicates": {kind: [g.to_dict() for g in groups] for kind, groups in duplicates.items()},
        "creator_concentration": _creator_concentration(records),
        "version_distributions": versions,
        "cost_latency": _cost_latency(records),
        "human_review": {
            **review_summary,
            "reviewed_video_count": len(reviewed_ids),
        },
    }
    return report


def write_audit_report(report: dict[str, Any], output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(canonical_json(report) + "\n")
    return output_path


def run_audit(dataset_root: Path, output_path: Path, reviews_root: Path | None = None) -> Path:
    report = audit_dataset(dataset_root, reviews_root)
    return write_audit_report(report, output_path)
