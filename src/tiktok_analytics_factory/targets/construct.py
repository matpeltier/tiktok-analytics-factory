"""Deterministic, leakage-safe target construction primitives.

Conventions:
- ``None`` means unknown/unavailable. Zero is never used to mean unknown.
- A zero denominator yields ``None`` (undefined ratio), not 0 and not an error,
  because 0 views is a legitimate observation that makes ratios undefined.
- Creator baselines are always computed leave-one-out: the target video never
  contributes to its own baseline.
- All functions are pure and deterministic given their inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from statistics import median

from .models import InvalidTargetError


def log1p_views(views: float | None) -> float | None:
    """``log1p(views)``; ``None`` input stays ``None`` (unknown is not zero)."""
    if views is None:
        return None
    v = float(views)
    if v < 0 or math.isnan(v):
        raise InvalidTargetError(f"views must be a non-negative number, got {views!r}")
    return math.log1p(v)


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    """Nullable division: unknown operands or a zero denominator give ``None``."""
    if numerator is None or denominator is None:
        return None
    num, den = float(numerator), float(denominator)
    if den == 0:
        return None
    return num / den


def engagement_ratios(
    views: int | None,
    likes: int | None,
    comments: int | None,
    shares: int | None,
) -> dict[str, float | None]:
    return {
        "likes_per_view": safe_ratio(likes, views),
        "comments_per_view": safe_ratio(comments, views),
        "shares_per_view": safe_ratio(shares, views),
    }


def _parse_iso(ts: str | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromisoformat(ts)


def post_age_days(published_at: str | None, observed_at: str | None) -> float | None:
    """Post age in days at observation time; ``None`` when either end is unknown."""
    pub, obs = _parse_iso(published_at), _parse_iso(observed_at)
    if pub is None or obs is None:
        return None
    age = (obs - pub).total_seconds() / 86400.0
    if age < 0:
        raise InvalidTargetError(
            f"observed_at {observed_at!r} precedes published_at {published_at!r}"
        )
    return age


# ---------------------------------------------------------------------------
# Creator-relative targets (leave-one-out baselines)
# ---------------------------------------------------------------------------


def creator_baselines(
    observations: list[dict],
    *,
    min_other_videos: int = 2,
    trim_fraction: float = 0.0,
) -> dict[str, dict]:
    """Compute per-creator baseline log-view statistics from *other* videos.

    ``observations`` items need: ``creator_key``, ``video_id``, and ``views``
    (nullable). For each video the baseline uses only videos by the same
    creator other than itself (strict leave-one-out). A creator baseline entry
    is produced once at cohort level; consumers must select the entry computed
    from the video's siblings.

    Returns ``{creator_key: {"baseline_log_views": float|None, "eligible_video_ids": [...]}}``
    where ``baseline_log_views`` is the median over eligible videos, or ``None``
    if fewer than ``min_other_videos`` eligible videos exist.

    With ``trim_fraction > 0`` a trimmed mean is used instead of a median
    (fraction trimmed from each tail before averaging).
    """
    if not 0 <= trim_fraction < 0.5:
        raise InvalidTargetError(f"trim_fraction must be in [0, 0.5), got {trim_fraction}")

    by_creator: dict[str, list[tuple[str, float]]] = {}
    for obs in observations:
        key = obs.get("creator_key")
        vid = obs.get("video_id")
        lv = log1p_views(obs.get("views"))
        if not key or not vid or lv is None:
            continue
        by_creator.setdefault(key, []).append((vid, lv))

    result: dict[str, dict] = {}
    for key, pairs in by_creator.items():
        values = [lv for _, lv in pairs]
        # Cohort-level statistic over ALL of this creator's videos (documented;
        # per-video leave-one-out happens in creator_relative_log_views).
        ordered = sorted(values)
        t = int(len(ordered) * trim_fraction)
        core = ordered[t : len(ordered) - t] if t else ordered
        baseline = sum(core) / len(core) if core else None
        result[key] = {
            "baseline_log_views": baseline,
            "n_videos": len(values),
            "eligible_video_ids": sorted(vid for vid, _ in pairs),
        }
    return result


def creator_relative_log_views(
    *,
    video_id: str,
    views: int | None,
    sibling_observations: list[dict],
    min_other_videos: int = 2,
) -> tuple[float | None, float | None, int]:
    """Leave-one-out creator-relative target for one video.

    The baseline is the median ``log1p(views)`` over the creator's videos
    *excluding* ``video_id`` itself. Returns
    ``(target_or_None, baseline_or_None, n_other_videos)``. When the creator has
    fewer than ``min_other_videos`` *other* valid videos the target is ``None``
    (insufficient history); it is never approximated with the video itself.
    """
    target_lv = log1p_views(views)
    if target_lv is None:
        return None, None, 0
    others_raw = [
        log1p_views(o.get("views"))
        for o in sibling_observations
        if o.get("video_id") != video_id and o.get("creator_key") is not None
    ]
    others: list[float] = [v for v in others_raw if v is not None]
    if len(others) < min_other_videos:
        return None, None, len(others)
    baseline: float = median(others)
    return target_lv - baseline, baseline, len(others)


# ---------------------------------------------------------------------------
# Age-adjusted residual target (transparent OLS baseline)
# ---------------------------------------------------------------------------

AGE_MODEL_FEATURES = ("intercept", "log_post_age_days", "creator_baseline_log_views")


def _solve_linear_system(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for a small square system."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            raise InvalidTargetError("Age-baseline design matrix is singular")
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit_age_baseline(rows: list[dict], *, ridge: float = 1e-6) -> dict[str, float]:
    """Fit ``log1p(views) ~ 1 + log(post_age_days) + creator_baseline`` via OLS.

    Each row needs numeric ``log_views``, ``post_age_days`` (> 0) and optional
    ``creator_baseline_log_views`` (missing becomes feature value 0 and a
    separate indicator is added so imputation is explicit, not silent).
    Pure-Python normal equations with a tiny ridge for numerical stability.
    """
    if len(rows) < 10:
        raise InvalidTargetError(
            f"age-adjustment requires >= 10 usable rows, got {len(rows)}"
        )

    xs: list[list[float]] = []
    ys: list[float] = []
    for row in rows:
        age = row["post_age_days"]
        if age is None or age <= 0:
            raise InvalidTargetError("age-adjustment rows require positive post_age_days")
        has_base = row.get("creator_baseline_log_views") is not None
        xs.append([
            1.0,
            math.log(age),
            float(row["creator_baseline_log_views"]) if has_base else 0.0,
            0.0 if has_base else 1.0,
        ])
        ys.append(float(row["log_views"]))

    k = len(xs[0])
    xtx = [[sum(x[i] * x[j] for x in xs) + (ridge if i == j else 0.0) for j in range(k)]
           for i in range(k)]
    xty = [sum(x[i] * y for x, y in zip(xs, ys)) for i in range(k)]
    coefs = _solve_linear_system(xtx, xty)

    names = ("intercept", "log_post_age_days", "creator_baseline_log_views", "baseline_missing_indicator")
    ss_tot = sum((y - sum(ys) / len(ys)) ** 2 for y in ys)
    ss_res = sum((y - sum(c * x for c, x in zip(coefs, x))) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {**dict(zip(names, coefs)), "n_rows": float(len(rows)), "r_squared": r2}


def expected_log_views(model: dict[str, float], post_age_days: float,
                       creator_baseline_log_views: float | None) -> float | None:
    """Predicted ``log1p(views)`` from the fitted age baseline; ``None`` inputs
    are handled by the model's explicit missing-indicator, but a missing age is
    fatal to prediction."""
    if post_age_days is None or post_age_days <= 0:
        return None
    base = (
        float(creator_baseline_log_views)
        if creator_baseline_log_views is not None
        else 0.0
    )
    has = creator_baseline_log_views is not None
    x = [
        1.0,
        math.log(post_age_days),
        base,
        0.0 if has else 1.0,
    ]
    coefs = [
        model["intercept"],
        model["log_post_age_days"],
        model["creator_baseline_log_views"],
        model["baseline_missing_indicator"],
    ]
    return sum(c * v for c, v in zip(coefs, x))


def performance_residual(observed_log_views: float | None,
                         expected_log_views_: float | None) -> float | None:
    """``residual = observed - expected``; ``None`` if either side is unknown."""
    if observed_log_views is None or expected_log_views_ is None:
        return None
    return observed_log_views - expected_log_views_


# ---------------------------------------------------------------------------
# Pairwise labels
# ---------------------------------------------------------------------------


def pairwise_label(value_a: float | None, value_b: float | None,
                   margin: float) -> str:
    """Pairwise label between two comparable videos.

    Returns ``"a_gt_b"``, ``"b_gt_a"``, or ``"tie"`` when the difference is
    below ``margin``. Unknown values yield ``"invalid"`` (never fabricated).
    """
    if margin < 0:
        raise InvalidTargetError(f"margin must be non-negative, got {margin}")
    if value_a is None or value_b is None:
        return "invalid"
    diff = value_a - value_b
    if diff >= margin:
        return "a_gt_b"
    if diff <= -margin:
        return "b_gt_a"
    return "tie"


def sample_pairwise(
    records: list[dict],
    *,
    margin: float,
    max_pairs_per_video: int = 5,
    seed: int = 0,
) -> list[dict]:
    """Sample balanced pairwise labels from comparable videos.

    Only videos sharing a ``comparability_key`` (by default the creator key,
    because creator-relative targets are only comparable within a creator) are
    paired — never all O(n^2) combinations across the cohort. Each video is
    capped at ``max_pairs_per_video`` pairs so no hub video dominates.

    Returns records with ``video_a``, ``video_b``, ``value_a``, ``value_b`` and
    ``label`` from :func:`pairwise_label`.
    """
    import random

    rng = random.Random(seed)
    by_key: dict[str, list[dict]] = {}
    for r in records:
        if r.get("target_value") is None:
            continue
        by_key.setdefault(r.get("comparability_key") or "__none__", []).append(r)

    pair_count: dict[str, int] = {}
    pairs: list[dict] = []
    for key, group in sorted(by_key.items()):
        if len(group) < 2:
            continue
        candidates = [
            (group[i], group[j])
            for i in range(len(group))
            for j in range(i + 1, len(group))
        ]
        rng.shuffle(candidates)
        for a, b in candidates:
            if pair_count.get(a["video_id"], 0) >= max_pairs_per_video:
                continue
            if pair_count.get(b["video_id"], 0) >= max_pairs_per_video:
                continue
            label = pairwise_label(a["target_value"], b["target_value"], margin)
            pair_count[a["video_id"]] = pair_count.get(a["video_id"], 0) + 1
            pair_count[b["video_id"]] = pair_count.get(b["video_id"], 0) + 1
            pairs.append({
                "comparability_key": key,
                "video_a": a["video_id"],
                "video_b": b["video_id"],
                "value_a": a["target_value"],
                "value_b": b["target_value"],
                "label": label,
            })
    return pairs


# ---------------------------------------------------------------------------
# Deterministic versioning
# ---------------------------------------------------------------------------


def deterministic_method_version(config: dict) -> str:
    """Stable short hash of the target-construction configuration.

    Any change to parameters changes the version, so targets can be recomputed
    and verified byte-for-byte from stored inputs.
    """
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
