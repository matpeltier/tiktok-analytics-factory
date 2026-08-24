"""Tests wiring the real validated components into the pilot (CI-safe fakes)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

import tiktok_analytics_factory.multistep.runner as ms_runner
import tiktok_analytics_factory.perception.pipeline as percep_pipeline
import tiktok_analytics_factory.pipeline.runner as runner_mod
from tiktok_analytics_factory.pipeline.adapters import (
    canonical_projection_stage,
    performance_snapshot_stage,
)
from tiktok_analytics_factory.pipeline.cohort import load_cohort
from tiktok_analytics_factory.pipeline.retry import RetryPolicy
from tiktok_analytics_factory.pipeline.runner import PilotOptions, run_pilot
from tiktok_analytics_factory.pipeline.stages import (
    PipelineStageError,
    VideoContext,
)

# --- performance snapshot stage ------------------------------------------------

def _ctx(tmp_path: Path, metadata: dict) -> VideoContext:
    return VideoContext(
        url="https://www.tiktok.com/@c/video/1",
        video_id="1",
        cohort_id="pilot-001",
        cohort_version="1.0.0",
        record_dir=tmp_path / "records" / "1",
        ingestion={"video_id": "1", "metadata": metadata},
    )


def test_performance_snapshot_builds_v0_1_contract(tmp_path):
    ctx = _ctx(tmp_path, {
        "platform": "tiktok", "video_id": "1", "source_url": "https://x/v/1",
        "creator_handle": "@c", "creator_id": "c-id", "published_at": "2026-08-01T00:00:00+00:00",
        "views": 120000, "likes": 9000, "comments": 100, "shares": 40, "saves": None,
        "collected_at": "2026-08-20T00:00:00+00:00",
        "collector_name": "yt-dlp", "collector_version": "2025.01.01",
    })
    res = performance_snapshot_stage(ctx)
    assert res.ok
    snap = json.loads((tmp_path / "records/1/source/performance/performance_v0_1.json").read_text())
    assert snap["schema"] == {"name": "performance", "version": "0.1"}
    assert snap["metrics"]["views"] == 120000
    assert snap["age_since_publish_seconds"] > 0


def test_performance_snapshot_missing_views_fails_loudly(tmp_path):
    ctx = _ctx(tmp_path, {"platform": "tiktok", "video_id": "1"})
    with pytest.raises(PipelineStageError):
        performance_snapshot_stage(ctx)


# --- cohort loader accepts the approved issue-#7 shape --------------------------

def test_cohort_loader_accepts_approved_full_schema():
    repo_cfg = Path(__file__).resolve().parents[1] / "config" / "pilot_cohort.json"
    if not repo_cfg.exists():
        pytest.skip("approved cohort config not present")
    policy = load_cohort(repo_cfg)
    assert policy.max_videos == 50
    assert policy.niche


def test_cohort_loader_rejects_unapproved_config(tmp_path):
    p = tmp_path / "cohort.json"
    p.write_text(json.dumps({
        "cohort_id": "x", "version": "1", "niche_name": "n",
        "approval_status": "draft",
    }))
    with pytest.raises(ValueError, match="not approved"):
        load_cohort(p)


# --- full batch run through the default (validated) stages ----------------------

class _FakePerceptionManifest:
    pipeline_version: str = "v1"

    class _Shots:
        shots: ClassVar[list] = [{"shot_id": "shot_001"}]

    shots = _Shots()
    frames: ClassVar[list] = [{}]


@pytest.fixture
def live_env(tmp_path, monkeypatch):
    """Fake network/model boundaries; everything downstream is real code."""
    monkeypatch.setenv("MULTISTEP_MODEL_ID", "fake-model")

    class _Meta:
        def __init__(self, vid):
            self.vid = vid

        def to_json_dict(self):
            return {
                "platform": "tiktok", "video_id": self.vid,
                "source_url": f"https://www.tiktok.com/@c/video/{self.vid}",
                "creator_handle": "@c", "views": 50000, "likes": 1000,
                "comments": 10, "shares": 5, "saves": None,
                "published_at": None, "duration_seconds": 15.0,
                "collected_at": "2026-08-24T00:00:00+00:00",
                "collector_name": "fake", "collector_version": "1",
            }

    class _Result:
        def __init__(self, vid, artifact_dir):
            self.video_id = vid
            self.metadata = _Meta(vid)
            self.artifact_dir = artifact_dir

    def fake_ingest(url, output_root, **kwargs):
        vid = url.rstrip("/").rsplit("/", 1)[-1]
        d = Path(output_root) / vid
        d.mkdir(parents=True, exist_ok=True)
        (d / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
        (d / "manifest.json").write_text("{}")
        return _Result(vid, d)

    monkeypatch.setattr(runner_mod, "ingest", fake_ingest)

    def fake_run_perception(video_path, output_dir, config=None):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "media_facts.json").write_text("{}")
        (out / "shots.json").write_text(json.dumps({"shots": [{"shot_id": "shot_001"}]}))
        return _FakePerceptionManifest()

    def fake_run_multistep(config, video_path, video_id, source_metadata, run_id=None, **kw):
        run_dir = Path(config.decompilation_dir(video_id, run_id or "r"))
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "creative_ir.json").write_text("{}")
        (run_dir / "canonical_ir.json").write_text("{}")
        (run_dir / "validation.json").write_text(json.dumps({"valid": True}))
        (run_dir / "usage.json").write_text(json.dumps({"total_cost_usd": 0.05}))
        return {
            "run_id": run_id or "r", "directory": str(run_dir),
            "usage": {"total_cost_usd": 0.05, "total_latency_seconds": 1.5},
            "creative_ir": {}, "canonical_ir": {}, "model_calls": 2,
            "pipeline_version": "multistep_v1",
        }

    monkeypatch.setattr(percep_pipeline, "run_perception", fake_run_perception)
    monkeypatch.setattr(ms_runner, "run_multistep", fake_run_multistep)


def test_default_stages_run_end_to_end(tmp_path, live_env):
    cohort = tmp_path / "cohort.json"
    cohort.write_text(json.dumps({
        "cohort_id": "pilot-001", "version": "1.0.0", "niche": "n", "max_videos": 50,
    }))
    sources = tmp_path / "sources.csv"
    sources.write_text("url,video_id\nhttps://www.tiktok.com/@c/video/777,777\n")
    summary = run_pilot(
        cohort, sources, tmp_path / "dataset",
        options=PilotOptions(retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=0)),
    )
    rec = tmp_path / "dataset/records/777"
    assert summary.metrics["fully_processed"] == 1
    assert (rec / "source/video.mp4").exists()
    assert (rec / "source/manifest.json").exists()
    assert (rec / "perception/v1/shots.json").exists()
    assert (rec / "decompilation/creative_ir.json").exists()
    manifest = json.loads((rec / "record_manifest.json").read_text())
    assert manifest["status"] == "success"
    assert manifest["schema_versions"]["decompile"]
    assert manifest["model_ids"]["decompile"]
    rows_file = tmp_path / "dataset/index.parquet"
    assert rows_file.exists()
    report = json.loads((tmp_path / "dataset/pilot_report.json").read_text())
    assert report["gate_decision"] in {"ready-for-modeling-dataset", "decompiler-needs-more-work"}


def test_decompile_stage_surfaces_model_failure_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MULTISTEP_MODEL_ID", "fake-model")

    def boom(*a, **kw):
        raise ms_runner.MultiStepRunError("quota exhausted")

    monkeypatch.setattr(ms_runner, "run_multistep", boom)
    ctx = _ctx(tmp_path, {"video_id": "1", "views": 10})
    ctx.ingestion = {"video_id": "1", "metadata": {"video_id": "1", "views": 10}}
    (tmp_path / "records/1/source").mkdir(parents=True)
    (tmp_path / "records/1/source/video.mp4").write_bytes(b"x")
    from tiktok_analytics_factory.pipeline.adapters import decompile_stage

    with pytest.raises(PipelineStageError):
        decompile_stage(ctx)


def test_canonical_projection_requires_valid_validation(tmp_path):
    dest = tmp_path / "records/1/decompilation"
    dest.mkdir(parents=True)
    for name in ("creative_ir.json", "canonical_ir.json"):
        (dest / name).write_text("{}")
    (dest / "validation.json").write_text(json.dumps({"valid": False, "errors": ["bad"]}))
    ctx = _ctx(tmp_path, {"video_id": "1", "views": 1})
    with pytest.raises(PipelineStageError):
        canonical_projection_stage(ctx)
