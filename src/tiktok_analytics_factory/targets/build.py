"""Build derived performance targets from immutable Performance snapshots.

Reads the ingestion layout produced by issue #3:

    <input_root>/<video_id>/metadata.normalized.json          (canonical snapshot)
    <input_root>/<video_id>/metadata.normalized.<stamp>.json  (re-observations)

Raw snapshots are only ever read; targets are written to a separate derived
artifact with full provenance.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from ..ingestion.ingest import PACKAGE_VERSION
from .construct import (
    creator_relative_log_views,
    deterministic_method_version,
    engagement_ratios,
    expected_log_views,
    fit_age_baseline,
    log1p_views,
    performance_residual,
    post_age_days,
)
from .models import (
    AGE_POLICY,
    TARGET_SCHEMA_VERSION,
    InvalidTargetError,
    PerformanceTargetRecord,
)

DEFAULT_CONFIG = {
    "target_schema_version": TARGET_SCHEMA_VERSION,
    "age_policy": AGE_POLICY,
    "creator_baseline_statistic": "median_log1p_views_leave_one_out",
    "min_other_videos_for_creator_target": 2,
    "pairwise_margin_log_units": 0.25,
    "age_model_min_rows": 10,
    "age_model_features": [
        "log_post_age_days",
        "creator_baseline_log_views",
        "baseline_missing_indicator",
    ],
}


def load_snapshot_records(input_root: Path) -> list[dict]:
    """Load one observation record per video: the canonical snapshot plus the
    newest re-observation when one exists (newest observed_at wins)."""
    records: list[dict] = []
    for meta_path in sorted(input_root.glob("*/metadata.normalized*.json")):
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        if not payload.get("video_id"):
            raise InvalidTargetError(f"{meta_path} has no video_id")
        payload["_snapshot_file"] = str(meta_path.relative_to(input_root))
        records.append(payload)

    if not records:
        raise InvalidTargetError(
            f"No Performance snapshots found under {input_root}; refusing to "
            "build targets from an empty cohort."
        )

    latest: dict[str, dict] = {}
    for rec in records:
        vid = rec["video_id"]
        cur = latest.get(vid)
        if cur is None or (rec.get("collected_at") or "") > (cur.get("collected_at") or ""):
            latest[vid] = rec
    return [latest[vid] for vid in sorted(latest)]


def build_targets(
    input_root: Path,
    output_path: Path,
    *,
    cohort_id: str,
    cohort_version: str,
    code_revision: str | None = None,
    config: dict | None = None,
) -> dict:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    snapshots = load_snapshot_records(input_root)
    now = datetime.now(UTC).isoformat()

    observations = [
        {
            "video_id": s["video_id"],
            # creator_id preferred; handle as documented fallback key
            "creator_key": s.get("creator_id") or s.get("creator_handle"),
            "views": s.get("views"),
        }
        for s in snapshots
    ]
    # Strictly leave-one-out baseline per video: the video itself must never
    # contribute to its own creator baseline (used by both targets below).
    loo: dict[str, tuple[float | None, float | None, int]] = {}
    for s in snapshots:
        creator_key = s.get("creator_id") or s.get("creator_handle")
        sibs = [o for o in observations if o.get("creator_key") == creator_key] if creator_key else []
        loo[s["video_id"]] = creator_relative_log_views(
            video_id=s["video_id"],
            views=s.get("views"),
            sibling_observations=sibs,
            min_other_videos=cfg["min_other_videos_for_creator_target"],
        )

    age_rows = []
    for s in snapshots:
        lv = log1p_views(s.get("views"))
        base = loo[s["video_id"]][1]
        if lv is not None:
            age_rows.append({
                "video_id": s["video_id"],
                "post_age_days": post_age_days(s.get("published_at"), s.get("collected_at")),
                "log_views": lv,
                "creator_baseline_log_views": base,
            })

    age_model = None
    usable_age_rows = [r for r in age_rows if r["post_age_days"] is not None]
    try:
        age_model = fit_age_baseline(usable_age_rows)
    except InvalidTargetError:
        age_model = None  # recorded explicitly below; policy falls back

    method_version = deterministic_method_version(cfg)
    target_version = f"{TARGET_SCHEMA_VERSION}+method:{method_version}"

    out_records = []
    for obs, s in zip(observations, snapshots):
        reasons: list[str] = []
        creator_key = obs["creator_key"]
        if creator_key is None:
            reasons.append("missing_creator_identity")

        rel, baseline, n_others = loo[s["video_id"]]
        if s.get("views") is None:
            reasons.append("missing_views")
        elif rel is None and creator_key is not None:
            reasons.append("insufficient_creator_history")

        ratios = engagement_ratios(
            s.get("views"), s.get("likes"), s.get("comments"), s.get("shares")
        )
        age = post_age_days(s.get("published_at"), s.get("collected_at"))
        if age is None:
            reasons.append("missing_post_age_or_observation_time")

        exp_lv = None
        residual = None
        if age_model is not None and age is not None and s.get("views") is not None:
            exp_lv = expected_log_views(age_model, age, baseline)
            residual = performance_residual(log1p_views(s.get("views")), exp_lv)

        valid = len(reasons) == 0
        rec = PerformanceTargetRecord(
            video_id=s["video_id"],
            source_snapshot_id=s["_snapshot_file"],
            source_snapshot_version=s.get("collector_version") or "unknown",
            cohort_id=cohort_id,
            cohort_version=cohort_version,
            target_version=target_version,
            views=s.get("views"),
            likes=s.get("likes"),
            comments=s.get("comments"),
            shares=s.get("shares"),
            published_at=s.get("published_at"),
            observed_at=s.get("collected_at"),
            post_age_days=age,
            log_views=log1p_views(s.get("views")),
            likes_per_view=ratios["likes_per_view"],
            comments_per_view=ratios["comments_per_view"],
            shares_per_view=ratios["shares_per_view"],
            creator_key=creator_key,
            # Strictly leave-one-out baseline; never the video's own value.
            creator_baseline_log_views=baseline,
            n_creator_other_videos=n_others,
            expected_log_views_age_model=exp_lv,
            creator_relative_log_views=rel,
            performance_residual=residual,
            is_valid=valid,
            invalid_reasons=reasons,
            constructed_at=now,
            code_revision=code_revision or PACKAGE_VERSION,
            construction_config=cfg,
        )
        out_records.append(rec.to_json_dict())

    n_valid = sum(1 for r in out_records if r["is_valid"])
    artifact = {
        "artifact_type": "derived_performance_targets",
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "target_version": target_version,
        "cohort_id": cohort_id,
        "cohort_version": cohort_version,
        "constructed_at": now,
        "code_revision": out_records[0]["code_revision"] if out_records else None,
        "construction_config": cfg,
        "age_baseline_model": age_model,
        "age_policy_note": (
            "Explicit age adjustment applied via transparent OLS baseline on "
            "[log post age, creator baseline]; where repeated snapshots are "
            "unavailable and the model could not be fit, records lacking post "
            "age are marked invalid rather than compared unadjusted."
            if age_model is None else
            "Fixed-age snapshots unavailable; explicit age adjustment applied."
        ),
        "coverage": {
            "n_videos": len(out_records),
            "n_valid_primary_target": n_valid,
            "valid_fraction": round(n_valid / len(out_records), 4) if out_records else 0.0,
        },
        "invalid_reason_counts": _count_reasons(out_records),
        "records": out_records,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return artifact


def _count_reasons(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in records:
        for reason in r["invalid_reasons"]:
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 4:
        print(
            "usage: python -m tiktok_analytics_factory.targets.build "
            "<snapshot_input_root> <output_json> <cohort_id> <cohort_version>",
            file=sys.stderr,
        )
        return 2
    artifact = build_targets(
        Path(argv[0]),
        Path(argv[1]),
        cohort_id=argv[2],
        cohort_version=argv[3],
    )
    cov = artifact["coverage"]
    print(
        f"wrote {argv[1]}: {cov['n_valid_primary_target']}/{cov['n_videos']} valid "
        f"(version={artifact['target_version']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
