"""Pilot metrics aggregation and gate decision."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from .record import utc_now_iso

GATE_MIN_SUCCESS = 20
GATE_MIN_SUCCESS_RATE = 0.85
GATE_MIN_REVIEW_OVERALL = 4.0


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, round(pct / 100 * (len(s) - 1))))
    return s[idx]


def aggregate(rows: list[dict[str, Any]], requested: int) -> dict[str, Any]:
    successes = [r for r in rows if r["status"] == "success"]
    rejections = [r for r in rows if r["status"] == "rejected_by_cohort"]
    attempted = [r for r in rows if r["status"] != "rejected_by_cohort"]
    latencies = [float(r.get("total_latency_seconds") or 0.0) for r in successes]
    costs = [float(r.get("total_usage_cost_usd") or 0.0) for r in successes]
    schema_ok = [r for r in successes if r.get("schema_valid")]
    return {
        "generated_at": utc_now_iso(),
        "requested": requested,
        "cohort_rejections": len(rejections),
        "ingested": len([r for r in attempted if r["status"] != "ingestion_failed"]),
        "fully_processed": len(successes),
        "success_rate": (len(successes) / len(attempted)) if attempted else 0.0,
        "schema_validation_rate": (len(schema_ok) / len(successes)) if successes else 0.0,
        "p50_latency_seconds": percentile(latencies, 50),
        "p95_latency_seconds": percentile(latencies, 95),
        "mean_cost_usd": (sum(costs) / len(costs)) if costs else 0.0,
        "median_cost_usd": statistics.median(costs) if costs else 0.0,
        "total_cost_usd": sum(costs),
        "model_provider_failures": len(
            [r for r in rows if r.get("failure_category") == "model_provider"]
        ),
        "collection_failures": len(
            [r for r in rows if r["status"] == "ingestion_failed"]
        ),
        "manual_review": {},
        "error_counts_by_category": _count_errors(rows),
    }


def _count_errors(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        cat = r.get("failure_category")
        if r["status"] != "success" and cat:
            counts[cat] = counts.get(cat, 0) + 1
    return counts


def apply_manual_review(metrics: dict[str, Any], reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge manual review scores into metrics.

    Each review: {"video_id", "scores": {category: 1..5}, "errors": [category...]}.
    """
    if not reviews:
        return metrics
    overall = [
        statistics.mean(r["scores"].values())
        for r in reviews
        if r.get("scores")
    ]
    error_counts: dict[str, int] = dict(metrics.get("error_counts_by_category", {}))
    for r in reviews:
        for e in r.get("errors", []):
            error_counts[e] = error_counts.get(e, 0) + 1
    metrics["manual_review"] = {
        "reviewed_count": len(reviews),
        "video_ids": [r.get("video_id") for r in reviews],
        "average_overall": round(statistics.mean(overall), 3) if overall else None,
        "per_review": reviews,
    }
    metrics["error_counts_by_category"] = error_counts
    return metrics


def decide_gate(metrics: dict[str, Any]) -> tuple[str, list[str]]:
    """Return (decision, blocking_reasons)."""
    blockers: list[str] = []
    n_success = metrics["fully_processed"]
    if n_success < GATE_MIN_SUCCESS:
        blockers.append(f"only {n_success} fully-processed videos (< {GATE_MIN_SUCCESS})")
    if metrics["success_rate"] < GATE_MIN_SUCCESS_RATE:
        blockers.append(f"success rate {metrics['success_rate']:.2%} < {GATE_MIN_SUCCESS_RATE:.0%}")
    if metrics["schema_validation_rate"] < 1.0:
        blockers.append("CreativeIR/CanonicalIR validation below 100% among success records")
    review = metrics.get("manual_review") or {}
    avg = review.get("average_overall")
    if avg is None or avg < GATE_MIN_REVIEW_OVERALL:
        blockers.append(f"manual review average {avg} < {GATE_MIN_REVIEW_OVERALL}")
    decision = (
        "ready-for-modeling-dataset" if not blockers else "decompiler-needs-more-work"
    )
    return decision, blockers


def write_report(path: Path, metrics: dict[str, Any], decision: str, blockers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **metrics,
        "gate_decision": decision,
        "gate_blockers": blockers,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
