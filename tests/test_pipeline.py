"""Tests for the pilot pipeline (CI-safe: fakes only, no network/models)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tiktok_analytics_factory.pipeline.runner as runner_mod
from tiktok_analytics_factory.ingestion.ingest import ingest as real_ingest
from tiktok_analytics_factory.pipeline.cohort import CohortPolicy, load_cohort
from tiktok_analytics_factory.pipeline.index import build_index
from tiktok_analytics_factory.pipeline.record import RECORD_STATUSES, build_manifest
from tiktok_analytics_factory.pipeline.report import aggregate, apply_manual_review, decide_gate
from tiktok_analytics_factory.pipeline.retry import RetryPolicy, TransientError, run_with_retry
from tiktok_analytics_factory.pipeline.runner import PilotOptions, run_pilot
from tiktok_analytics_factory.pipeline.sources import SourceEntry, load_sources

from .pipeline_fixtures import FakeIngest, fail_stage, fake_stages


@pytest.fixture
def cohort(tmp_path: Path) -> Path:
    cfg = {
        "cohort_id": "pilot-001",
        "version": "1.0.0",
        "niche": "test-niche",
        "max_videos": 50,
        "rules": {"required_hashtags": ["exampletag"], "min_views": 10000},
    }
    p = tmp_path / "pilot_cohort.json"
    p.write_text(json.dumps(cfg))
    return p


def write_sources(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "sources.csv"
    cols = ["url", "video_id", "creator_handle", "hashtags", "views", "published_at"]
    lines = [",".join(cols)]
    for r in rows:
        lines.append(",".join(str(r.get(c, "")) for c in cols))
    p.write_text("\n".join(lines))
    return p


def url_for(vid: str) -> str:
    return f"https://www.tiktok.com/@c/video/{vid}"


def _run(tmp_path, sources_rows, stages=None, ingest=None, reprocess=False, cohort_file=None):
    cohort_p = cohort_file or (tmp_path / "cohort.json")
    if cohort_file is None and not Path(cohort_p).exists():
        cohort_p.write_text(json.dumps({
            "cohort_id": "pilot-001", "version": "1.0.0", "niche": "n",
            "max_videos": 50, "rules": {},
        }))
    src = write_sources(tmp_path, sources_rows)
    runner_mod.ingest, prev = (ingest or real_ingest), runner_mod.ingest
    try:
        return run_pilot(
            cohort_p, src, tmp_path / "dataset",
            stages=stages or fake_stages(),
            options=PilotOptions(resume=True, reprocess=reprocess,
                                 retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=0)),
        )
    finally:
        runner_mod.ingest = prev


# --- source loading -----------------------------------------------------------

def test_load_sources_csv(tmp_path):
    p = write_sources(tmp_path, [{"url": url_for("1"), "hashtags": "#a;#b", "views": 100}])
    entries = load_sources(p)
    assert len(entries) == 1
    assert entries[0].hashtags == ["a", "b"]
    assert entries[0].views == 100


def test_load_sources_jsonl(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"url": url_for("2")}) + "\n" + json.dumps({"url": url_for("3")}) + "\n")
    assert len(load_sources(p)) == 2


def test_load_sources_rejects_missing_url_and_duplicates(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("url\n\n")
    with pytest.raises(ValueError):
        load_sources(bad)
    dup = tmp_path / "dup.csv"
    dup.write_text(f"url\n{url_for('9')}\n{url_for('9')}\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_sources(dup)


# --- cohort -------------------------------------------------------------------

def test_cohort_accept_and_reject(cohort):
    policy = load_cohort(cohort)
    ok = policy.check(SourceEntry(url=url_for("1"), hashtags=["exampletag"], views=20000))
    no_tag = policy.check(SourceEntry(url=url_for("2"), hashtags=["other"], views=20000))
    low = policy.check(SourceEntry(url=url_for("3"), hashtags=["exampletag"], views=5))
    assert ok.accepted
    assert not no_tag.accepted and "hashtag" in no_tag.reason
    assert not low.accepted and "views_below_min" in low.reason


def test_cohort_max_enforced():
    with pytest.raises(ValueError):
        CohortPolicy.from_dict(
            {"cohort_id": "x", "version": "1", "niche": "n", "max_videos": 60, "rules": {}}
        )


# --- bounded retry ------------------------------------------------------------

def test_bounded_retry_succeeds_then_exhausts():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("timeout")
        return "ok"

    out = run_with_retry(flaky, RetryPolicy(max_attempts=3, backoff_seconds=0), sleep=lambda s: None)
    assert out.succeeded and out.value == "ok" and out.attempts == 3

    def always():
        raise TransientError("rate limit")

    out2 = run_with_retry(always, RetryPolicy(max_attempts=2, backoff_seconds=0), sleep=lambda s: None)
    assert not out2.succeeded and out2.attempts == 2


# --- manifest -----------------------------------------------------------------

def test_manifest_creation():
    from tiktok_analytics_factory.pipeline.stages import StageResult

    entry = SourceEntry(url=url_for("5"), video_id="5")
    m = build_manifest(
        entry=entry,
        cohort_id="c",
        cohort_version="v1",
        status="success",
        stage_results={
            "perception": StageResult(ok=True, usage_cost_usd=0.02, latency_seconds=1.0,
                                      model_id="m", prompt_version="pv", schema_version="sv"),
        },
        pipeline_version="pilot-test",
        source_hash="src-hash",
        video_hash="vid-hash",
    )
    assert m["status"] == "success"
    assert m["total_usage_cost_usd"] == 0.02
    assert m["total_latency_seconds"] == 1.0
    assert m["model_ids"] == {"perception": "m"}
    assert m["prompt_versions"] == {"perception": "pv"}
    assert m["schema_versions"] == {"perception": "sv"}
    assert m["source_hash"] == "src-hash"


# --- full runner with fakes ---------------------------------------------------

def test_successful_video_end_to_end(tmp_path):
    summary = _run(tmp_path, [
        {"url": url_for("101"), "video_id": "101", "hashtags": "exampletag"},
    ], ingest=FakeIngest())
    row = summary.rows[0]
    assert row["status"] == "success"
    rec = tmp_path / "dataset" / "records" / "101"
    assert (rec / "record_manifest.json").exists()
    assert (rec / "source" / "metadata.normalized.json").exists()
    manifest = json.loads((rec / "record_manifest.json").read_text())
    assert manifest["status"] == "success"
    assert manifest["cohort_id"] == "pilot-001"
    assert manifest["schema_valid"] is True
    assert (tmp_path / "dataset" / "index.parquet").exists()


def test_failure_isolation_success_and_failed_coexist(tmp_path):
    stages = fake_stages()
    original = stages.decompile

    def selective_decompile(ctx):
        if ctx.video_id == "202":
            raise PipelineStageError("decompile", "model_provider", "provider down")
        return original(ctx)

    stages.decompile = selective_decompile
    summary = _run(
        tmp_path,
        [
            {"url": url_for("201"), "video_id": "201"},
            {"url": url_for("202"), "video_id": "202"},
        ],
        stages=stages,
        ingest=FakeIngest(),
    )
    statuses = {r["video_id"]: r["status"] for r in summary.rows}
    assert statuses == {"201": "success", "202": "decompilation_failed"}
    rows = build_index(tmp_path / "dataset" / "records", tmp_path / "idx.parquet")
    assert {r["status"] for r in rows} == {"success", "decompilation_failed"}


def test_ingestion_failed_status(tmp_path):
    summary = _run(
        tmp_path,
        [{"url": url_for("301"), "video_id": "301"}],
        ingest=FakeIngest(fail_urls={url_for("301")}),
    )
    assert summary.rows[0]["status"] == "ingestion_failed"


def test_cohort_rejection_persisted_with_reason(tmp_path):
    cohort_p = tmp_path / "cohort.json"
    cohort_p.write_text(json.dumps({
        "cohort_id": "c", "version": "1", "niche": "n", "max_videos": 50,
        "rules": {"required_hashtags": ["exampletag"]},
    }))
    src = write_sources(tmp_path, [{"url": url_for("401"), "hashtags": "wrong"}])
    summary = run_pilot(cohort_p, src, tmp_path / "ds", stages=fake_stages(),
                        options=PilotOptions(retry_policy=RetryPolicy(max_attempts=1)))
    assert summary.rows[0]["status"] == "rejected_by_cohort"
    rej = tmp_path / "ds" / "rejected_sources.jsonl"
    payload = json.loads(rej.read_text().splitlines()[0])
    assert "missing_required_hashtag" in payload["reason"]
    # rejected videos must never be ingested
    assert not (tmp_path / "ds" / "records").exists()


def test_resumable_rerun_skips_success(tmp_path):
    vid_row = [{"url": url_for("501"), "video_id": "501"}]
    fake = FakeIngest()
    _run(tmp_path, vid_row, ingest=fake)
    first_calls = fake.calls
    summary = _run(tmp_path, vid_row, ingest=fake)
    assert fake.calls == first_calls  # skipped on resume
    assert summary.rows[0]["status"] == "success"

    _run(tmp_path, vid_row, ingest=fake, reprocess=True)
    assert fake.calls > first_calls  # actually reprocessed when explicit


def test_metrics_aggregation_and_gate(tmp_path):
    summary = _run(
        tmp_path,
        [{"url": url_for(str(i)), "video_id": str(i)} for i in range(601, 606)],
        ingest=FakeIngest(),
    )
    metrics = summary.metrics
    assert metrics["requested"] == 5
    assert metrics["fully_processed"] == 5
    assert metrics["success_rate"] == 1.0
    assert metrics["total_cost_usd"] > 0
    assert metrics["p50_latency_seconds"] > 0
    decision, blockers = decide_gate(metrics)
    # Only 5 videos: cannot pass the >=20 gate even at 100% success.
    assert decision == "decompiler-needs-more-work"
    assert any("< 20" in b for b in blockers)


def test_manual_review_applied():
    metrics = aggregate([], requested=0)
    metrics.update({
        "fully_processed": 25, "success_rate": 1.0, "schema_validation_rate": 1.0,
    })
    reviews = [
        {"video_id": "a", "scores": {"media_facts": 4, "hook_narrative": 5}, "errors": []},
        {"video_id": "b", "scores": {"dialogue": 4, "reconstruction": 4}, "errors": ["OCR/on-screen text"]},
    ]
    metrics = apply_manual_review(metrics, reviews)
    assert metrics["manual_review"]["average_overall"] == 4.25
    assert metrics["error_counts_by_category"]["OCR/on-screen text"] == 1


def test_required_statuses_defined():
    assert {
        "success", "rejected_by_cohort", "ingestion_failed",
        "perception_failed", "decompilation_failed", "validation_failed",
    } <= RECORD_STATUSES
