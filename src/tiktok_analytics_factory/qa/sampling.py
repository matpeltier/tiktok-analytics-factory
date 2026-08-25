"""Deterministic sampling helpers so manual QA is not biased toward easy or
high-performing videos.

All functions are pure and deterministic given the same inputs: candidate
records are sorted by video_id before any seeded random choice is made.
"""

from __future__ import annotations

import math
import random
from typing import Any, Iterable, Sequence

from .records import DatasetRecord
from .validators import run_validators


def _sorted_by_id(records: Iterable[DatasetRecord]) -> list[DatasetRecord]:
    return sorted(records, key=lambda r: r.video_id)


def filter_records(
    records: Sequence[DatasetRecord],
    *,
    creator: str | None = None,
    status: str | None = None,
    pipeline_version: str | None = None,
    model_version: str | None = None,
    qa_category: str | None = None,
) -> list[DatasetRecord]:
    """Deterministically filter records by manifest/validator attributes."""
    out: list[DatasetRecord] = []
    for rec in _sorted_by_id(records):
        if creator is not None and rec.creator != creator:
            continue
        if status is not None and rec.status != status:
            continue
        if pipeline_version is not None and rec.manifest.get("pipeline_version") != pipeline_version:
            continue
        if model_version is not None:
            model_ids = {
                rec.manifest.get("model_id"),
                (rec.creative_ir or {}).get("model_id") if rec.creative_ir else None,
            }
            if model_version not in model_ids:
                continue
        if qa_category is not None:
            cats = {issue.category for issue in run_validators(rec)}
            if qa_category not in cats:
                continue
        out.append(rec)
    return out


def performance_quantile(
    records: Sequence[DatasetRecord],
    metric_key: str = "views",
    q: float = 0.9,
) -> float | None:
    """Return the q-quantile of a raw metric across records that have it."""
    values = sorted(
        v
        for v in (
            ((rec.performance or {}).get("snapshots") or [{}])[-1].get("metrics", {}).get(metric_key)
            for rec in records
            if rec.performance
        )
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    )
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return float(values[lo])
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def sample_records(
    records: Sequence[DatasetRecord],
    *,
    seed: int | None = None,
    limit: int = 10,
    min_metric: tuple[str, float] | None = None,
    max_metric: tuple[str, float] | None = None,
    **filters: Any,
) -> list[DatasetRecord]:
    """Deterministically sample up to ``limit`` records.

    ``min_metric``/``max_metric`` are ``(metric_key, value)`` pairs applied to
    the latest performance snapshot, enabling e.g. performance-quantile slices.
    All other keyword arguments are passed to :func:`filter_records`.
    """
    candidates = filter_records(records, **filters)
    if min_metric is not None or max_metric is not None:
        bound = min_metric if min_metric is not None else max_metric
        assert bound is not None

        def metric_of(rec: DatasetRecord) -> Any:
            key = bound[0]
            snaps = (rec.performance or {}).get("snapshots") or []
            if snaps:
                return snaps[-1].get("metrics", {}).get(key)
            return None

        def keep(rec: DatasetRecord) -> bool:
            m = metric_of(rec)
            if not isinstance(m, (int, float)) or isinstance(m, bool):
                return False
            if min_metric is not None and m < min_metric[1]:
                return False
            if max_metric is not None and m > max_metric[1]:
                return False
            return True

        candidates = [r for r in candidates if keep(r)]

    if len(candidates) <= limit:
        return candidates
    rng = random.Random(seed)
    picked = set(rng.sample(range(len(candidates)), limit))
    return [candidates[i] for i in sorted(picked)]
