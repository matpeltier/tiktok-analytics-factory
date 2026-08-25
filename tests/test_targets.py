"""Tests for leakage-safe performance-target construction (issue #9)."""

from __future__ import annotations

import json
import math
from datetime import UTC
from pathlib import Path

import pytest

from tiktok_analytics_factory.targets.build import (
    DEFAULT_CONFIG,
    build_targets,
    load_snapshot_records,
)
from tiktok_analytics_factory.targets.construct import (
    creator_baselines,
    creator_relative_log_views,
    deterministic_method_version,
    engagement_ratios,
    expected_log_views,
    fit_age_baseline,
    log1p_views,
    pairwise_label,
    performance_residual,
    post_age_days,
    safe_ratio,
    sample_pairwise,
)
from tiktok_analytics_factory.targets.models import InvalidTargetError

# ---------------------------------------------------------------------------
# Zero vs unknown
# ---------------------------------------------------------------------------


def test_unknown_views_stay_none_not_zero():
    assert log1p_views(None) is None
    assert safe_ratio(None, 10) is None
    assert safe_ratio(5, None) is None


def test_zero_denominator_yields_none_not_zero():
    assert safe_ratio(3, 0) is None
    ratios = engagement_ratios(views=0, likes=10, comments=2, shares=1)
    assert ratios == {
        "likes_per_view": None,
        "comments_per_view": None,
        "shares_per_view": None,
    }


def test_zero_views_is_legitimate_for_log_but_undefined_for_ratio():
    assert log1p_views(0) == 0.0
    assert engagement_ratios(0, 0, 0, 0)["likes_per_view"] is None


def test_negative_views_fail_loudly():
    with pytest.raises(InvalidTargetError):
        log1p_views(-1)


# ---------------------------------------------------------------------------
# Log transforms
# ---------------------------------------------------------------------------


def test_log1p_matches_math_log1p():
    for v in (0, 1, 9, 1500000):
        assert log1p_views(v) == pytest.approx(math.log1p(v))


# ---------------------------------------------------------------------------
# Post age
# ---------------------------------------------------------------------------


def test_post_age_none_when_either_end_missing():
    assert post_age_days(None, "2026-08-24T00:00:00Z") is None
    assert post_age_days("2026-08-01T00:00:00Z", None) is None


def test_post_age_computation_and_negative_guard():
    days = post_age_days("2026-08-10T00:00:00+00:00", "2026-08-24T12:00:00+00:00")
    assert days == pytest.approx(14.5)
    with pytest.raises(InvalidTargetError):
        post_age_days("2026-08-24T00:00:00Z", "2026-08-01T00:00:00Z")


# ---------------------------------------------------------------------------
# Creator baseline: leave-one-out behavior
# ---------------------------------------------------------------------------


def _obs(vid, views, creator="c1"):
    return {"video_id": vid, "creator_key": creator, "views": views}


def test_leave_one_out_excludes_target_from_own_baseline():
    siblings = [_obs("v1", 100), _obs("v2", 1000), _obs("v3", 1000000)]
    rel, baseline, n = creator_relative_log_views(
        video_id="v2", views=1000, sibling_observations=siblings
    )
    # baseline must be median of {log1p(100), log1p(1000000)} — v2 excluded
    expected_base = (math.log1p(100) + math.log1p(1000000)) / 2
    assert n == 2
    assert baseline == pytest.approx(expected_base)
    assert rel == pytest.approx(math.log1p(1000) - expected_base)


def test_no_target_row_leaks_into_own_creator_baseline():
    # A single extreme target video must not shift its own baseline.
    sibs = [_obs("t", 10**7), _obs("a", 100), _obs("b", 121)]
    _, base_with_extreme_self, _ = creator_relative_log_views(
        video_id="t", views=10**7, sibling_observations=sibs
    )
    # baseline over siblings {a:100, b:121} — t's own extreme views excluded
    expected_base = (math.log1p(100) + math.log1p(121)) / 2
    assert base_with_extreme_self == pytest.approx(expected_base)


def test_insufficient_history_gives_none():
    siblings = [_obs("v1", 100), _obs("v2", 200)]
    rel, base, n = creator_relative_log_views(
        video_id="v1", views=100, sibling_observations=siblings, min_other_videos=2
    )
    assert rel is None and base is None and n == 1


def test_cohort_level_baselines_skip_null_views():
    out = creator_baselines([_obs("a", 10), _obs("b", None), _obs("c", 30)])
    assert out["c1"]["n_videos"] == 2
    assert out["c1"]["baseline_log_views"] == pytest.approx((math.log1p(10) + math.log1p(30)) / 2)


# ---------------------------------------------------------------------------
# Age-adjusted residual
# ---------------------------------------------------------------------------


def _age_rows(n=12):
    # Exact linear ground truth: lv = 5 + 2*log(age) + 0.3*baseline
    rows = []
    for i in range(n):
        age = 1.0 + i
        base = 5.0 + (i % 3)
        rows.append({
            "video_id": f"v{i}",
            "post_age_days": float(age),
            "log_views": 5.0 + 2.0 * math.log(age) + 0.3 * base,
            "creator_baseline_log_views": base,
        })
    return rows


def test_age_model_requires_minimum_rows_and_positive_ages():
    with pytest.raises(InvalidTargetError):
        fit_age_baseline(_age_rows()[:5])
    bad = _age_rows()
    bad[0]["post_age_days"] = 0.0
    with pytest.raises(InvalidTargetError):
        fit_age_baseline(bad)


def test_age_model_recovers_linear_signal_and_residual_is_zero_on_train():
    model = fit_age_baseline(_age_rows())
    assert model["intercept"] == pytest.approx(5.0, abs=1e-3)
    assert model["log_post_age_days"] == pytest.approx(2.0, abs=1e-3)
    assert model["creator_baseline_log_views"] == pytest.approx(0.3, abs=1e-3)
    row = _age_rows()[3]
    exp = expected_log_views(model, row["post_age_days"],
                             row["creator_baseline_log_views"])
    assert exp == pytest.approx(row["log_views"])
    assert performance_residual(row["log_views"], exp) == pytest.approx(0.0, abs=1e-4)


def test_expected_log_views_handles_missing_baseline_via_indicator():
    model = fit_age_baseline(_age_rows())
    e_with = expected_log_views(model, 4.0, 5.0)
    e_without = expected_log_views(model, 4.0, None)
    assert e_without != pytest.approx(e_with)
    assert expected_log_views(model, 0.0, 5.0) is None
    assert expected_log_views(model, None, 5.0) is None
    assert performance_residual(None, e_with) is None


# ---------------------------------------------------------------------------
# Pairwise labels and sampling
# ---------------------------------------------------------------------------


def test_pairwise_margin_and_tie_handling():
    assert pairwise_label(2.0, 1.0, margin=0.25) == "a_gt_b"
    assert pairwise_label(1.0, 2.0, margin=0.25) == "b_gt_a"
    assert pairwise_label(1.1, 1.0, margin=0.25) == "tie"
    assert pairwise_label(1.25, 1.0, margin=0.25) == "a_gt_b"
    assert pairwise_label(None, 1.0, margin=0.25) == "invalid"
    with pytest.raises(InvalidTargetError):
        pairwise_label(1.0, 1.0, margin=-1)


def test_pairwise_sampling_only_within_comparability_key_and_deterministic():
    recs = [
        {"video_id": f"a{i}", "comparability_key": "A", "target_value": float(i)}
        for i in range(6)
    ] + [
        {"video_id": f"b{i}", "comparability_key": "B", "target_value": float(i)}
        for i in range(6)
    ]
    p1 = sample_pairwise(recs, margin=0.25, max_pairs_per_video=3, seed=7)
    p2 = sample_pairwise(recs, margin=0.25, max_pairs_per_video=3, seed=7)
    assert p1 == p2  # deterministic given seed
    keys = {(p["video_a"][0], p["video_b"][0]) for p in p1}
    assert keys <= {("a", "a"), ("b", "b")}  # never cross-group pairs
    counts: dict[str, int] = {}
    for p in p1:
        counts[p["video_a"]] = counts.get(p["video_a"], 0) + 1
        counts[p["video_b"]] = counts.get(p["video_b"], 0) + 1
    assert all(c <= 3 for c in counts.values())  # per-video cap respected
    labels = {p["label"] for p in p1}
    assert labels <= {"a_gt_b", "b_gt_a", "tie"}
    # invalid targets are excluded entirely
    p3 = sample_pairwise(recs + [{"video_id": "x", "comparability_key": "A",
                                  "target_value": None}], margin=0.25)
    assert all("x" not in (p["video_a"], p["video_b"]) for p in p3)


# ---------------------------------------------------------------------------
# Deterministic versioning
# ---------------------------------------------------------------------------


def test_method_version_is_stable_and_config_sensitive():
    cfg = {"a": 1, "b": [1, 2]}
    v1 = deterministic_method_version(cfg)
    assert v1 == deterministic_method_version({"b": [1, 2], "a": 1})  # key order irrelevant
    assert v1 != deterministic_method_version({**cfg, "a": 2})
    assert len(v1) == 12


# ---------------------------------------------------------------------------
# Build pipeline on a synthetic snapshot layout
# ---------------------------------------------------------------------------


@pytest.fixture()
def snapshot_root(tmp_path: Path) -> Path:
    vids = [
        ("v1", "cr_a", 500, 40, 3.0),
        ("v2", "cr_a", 900, 50, 8.0),
        ("v3", "cr_a", 700, 45, 20.0),
        ("v4", "cr_b", 1200, 60, 5.0),
        ("v5", "cr_b", 1300, 61, 15.0),
        ("v6", "cr_b", 1100, 59, 40.0),
        ("v7", "cr_c", 1500, 70, 12.0),
        ("v8", "cr_c", 1600, 71, 18.0),
        ("v9", "cr_c", 1400, 69, 26.0),
        ("solo", "cr_solo", 800, 30, 10.0),      # insufficient history
        ("noage", "cr_a", 600, 41, None),        # missing published_at
        ("noviews", "cr_a", None, 42, 30.0),     # missing views
        ("nocreator", None, 650, 43, 25.0),      # missing creator identity
    ]
    obs = "2026-08-24T12:00:00+00:00"
    for vid, cr, views, likes, age in vids:
        d = tmp_path / vid
        d.mkdir()
        payload = {
            "platform": "tiktok",
            "video_id": vid,
            "creator_handle": cr,
            "creator_id": cr,
            "views": views,
            "likes": likes,
            "comments": 1 if views else None,
            "shares": 2 if views else None,
            "collected_at": obs,
            "collector_version": "test-1",
        }
        if age is not None:
            from datetime import datetime, timedelta

            payload["published_at"] = (
                datetime(2026, 8, 24, tzinfo=UTC) - timedelta(days=age)
            ).isoformat()
        (d / "metadata.normalized.json").write_text(json.dumps(payload))
    return tmp_path


def test_build_targets_validity_and_coverage(snapshot_root: Path, tmp_path: Path):
    out = tmp_path / "targets.json"
    artifact = build_targets(snapshot_root, out, cohort_id="coh", cohort_version="v1")
    by_id = {r["video_id"]: r for r in artifact["records"]}

    assert set(by_id) == {"v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9",
                          "solo", "noage", "noviews", "nocreator"}

    # explicit invalid reasons rather than fabricated values
    assert "insufficient_creator_history" in by_id["solo"]["invalid_reasons"]
    assert "missing_post_age_or_observation_time" in by_id["noage"]["invalid_reasons"]
    assert "missing_views" in by_id["noviews"]["invalid_reasons"]
    assert "missing_creator_identity" in by_id["nocreator"]["invalid_reasons"]
    assert not by_id["solo"]["is_valid"] and not by_id["noviews"]["is_valid"]

    # valid core records carry full provenance and intermediate quantities
    r = by_id["v2"]
    assert r["is_valid"]
    assert r["target_schema_version"] == "performance_target_v0_1"
    assert r["source_snapshot_id"].endswith("metadata.normalized.json")
    assert r["cohort_id"] == "coh" and r["cohort_version"] == "v1"
    assert r["target_version"].startswith("performance_target_v0_1+method:")
    assert r["constructed_at"] and r["code_revision"]
    assert r["construction_config"] == DEFAULT_CONFIG
    assert r["post_age_days"] == pytest.approx(8.5)
    assert r["log_views"] == pytest.approx(math.log1p(900))
    # leave-one-out baseline over cr_a's other videos with known views
    # (v1=500, v3=700, noage=600; v2 itself and noviews excluded)
    import statistics

    expected = statistics.median([math.log1p(v) for v in (500, 700, 600)])
    assert r["creator_baseline_log_views"] == pytest.approx(expected)
    assert r["creator_relative_log_views"] == pytest.approx(math.log1p(900) - expected)
    assert r["likes_per_view"] == pytest.approx(50 / 900)
    assert r["expected_log_views_age_model"] is not None
    assert r["performance_residual"] is not None

    cov = artifact["coverage"]
    assert cov["n_videos"] == 13
    assert cov["n_valid_primary_target"] == 9
    assert artifact["invalid_reason_counts"] == {
        "insufficient_creator_history": 1,
        "missing_post_age_or_observation_time": 1,
        "missing_views": 1,
        "missing_creator_identity": 1,
    }
    assert out.exists()


def test_build_targets_reproducible_from_stored_inputs(
    snapshot_root: Path, tmp_path: Path
):
    a = build_targets(snapshot_root, tmp_path / "a.json",
                      cohort_id="c", cohort_version="1")
    b = build_targets(snapshot_root, tmp_path / "b.json",
                      cohort_id="c", cohort_version="1")
    strip = lambda art: [{k: v for k, v in r.items()
                          if k not in ("constructed_at",)}
                         for r in art["records"]]
    assert strip(a) == strip(b)
    assert a["age_baseline_model"] == b["age_baseline_model"]


def test_load_snapshot_records_picks_newest_observation(tmp_path: Path):
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1" / "metadata.normalized.json").write_text(json.dumps({
        "video_id": "v1", "views": 100, "collected_at": "2026-08-01T00:00:00+00:00"}))
    (tmp_path / "v1" / "metadata.normalized.20260802.json").write_text(json.dumps({
        "video_id": "v1", "views": 400, "collected_at": "2026-08-02T00:00:00+00:00"}))
    recs = load_snapshot_records(tmp_path)
    assert len(recs) == 1 and recs[0]["views"] == 400


def test_empty_snapshot_root_fails_loudly(tmp_path: Path):
    with pytest.raises(InvalidTargetError):
        build_targets(tmp_path, tmp_path / "out.json",
                      cohort_id="c", cohort_version="1")
