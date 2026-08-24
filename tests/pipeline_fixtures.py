"""Shared fakes for pilot pipeline tests (CI uses no network/models)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tiktok_analytics_factory.pipeline.stages import (
    PipelineStages,
    StageResult,
    VideoContext,
)


def make_metadata_dict(video_id: str, views: int) -> dict:
    return {
        "platform": "tiktok",
        "video_id": video_id,
        "source_url": f"https://www.tiktok.com/@creator_{video_id}/video/{video_id}",
        "creator_handle": f"@creator_{video_id[:2]}",
        "creator_id": f"cid-{video_id}",
        "views": views,
        "likes": views // 10,
        "comments": views // 100,
        "shares": views // 200,
        "duration_seconds": 21.5,
        "published_at": "2026-06-01T00:00:00+00:00",
    }


@dataclass
class FakeIngestResult:
    video_id: str
    metadata: object
    artifact_dir: Path


class FakeIngest:
    """Monkeypatch target for tiktok_analytics_factory.pipeline.runner.ingest."""

    def __init__(self, fail_urls: set[str] | None = None):
        self.fail_urls = fail_urls or set()
        self.calls = 0

    def __call__(self, url: str, output_root: str, **kwargs):
        self.calls += 1
        if url in self.fail_urls:
            raise RuntimeError(f"collection timeout for {url}")
        vid = url.rstrip("/").rsplit("/", 1)[-1]
        return FakeIngestResult(
            video_id=vid,
            metadata=type("M", (), {"to_json_dict": lambda s: make_metadata_dict(vid, 50000)})(),
            artifact_dir=Path(output_root),
        )


def ok_stage(name: str, artifacts: dict | None = None):
    def run(ctx: VideoContext) -> StageResult:
        return StageResult(
            ok=True,
            artifacts=artifacts or {},
            usage_cost_usd=0.01,
            latency_seconds=0.5,
            model_id="fake-model",
            prompt_version=f"{name}-prompt-v1",
            schema_version="1",
        )

    return run


def fake_decompile():
    """Successful decompile fake that persists validation artifacts like the
    real adapter, so schema_valid can be derived from them."""

    def run(ctx: VideoContext) -> StageResult:
        dest = Path(ctx.record_dir) / "decompilation"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "creative_ir.json").write_text(json.dumps({"schema": "creative_ir/0.1"}))
        (dest / "canonical_ir.json").write_text(json.dumps({"schema": "canonical_ir/0.1"}))
        (dest / "validation.json").write_text(json.dumps({"valid": True, "errors": []}))
        return StageResult(
            ok=True,
            artifacts={"validation": "pass"},
            usage_cost_usd=0.02,
            latency_seconds=0.5,
            model_id="fake-model",
            prompt_version="decompile-prompt-v1",
            schema_version="1",
        )

    return run


def fail_stage(category: str):
    def run(ctx: VideoContext) -> StageResult:
        return StageResult(ok=False, error_category=category, error_message="boom")

    return run


def fake_stages(perception=ok_stage("perception"), decompile=None):
    return PipelineStages(
        performance_snapshot=ok_stage("performance"),
        perception=perception,
        decompile=decompile or fake_decompile(),
        project_canonical=ok_stage("canonical", artifacts={"observed_at": "2026-08-24T00:00:00+00:00"}),
    )
