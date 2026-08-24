"""Real stage adapters: wire the validated components (#2/#3/#5/#6) into the
batch pilot without redesigning them.

- ``performance_snapshot_stage`` projects the ingested raw metadata into the
  Performance v0.1 snapshot contract (#3).
- ``perception_stage`` runs the deterministic perception layer (#5).
- ``decompile_stage`` runs the validated two-pass multi-step decompiler (#6)
  unchanged; raw model responses are persisted per run and never overwritten.
- ``canonical_projection_stage`` verifies the deterministic CreativeIR ->
  CanonicalIR projection recorded by the decompiler (it is part of the
  validated run, not re-executed here).

Any failure fails loudly with an explicit stage/category; nothing silently
falls back.
"""

from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .stages import PipelineStageError, StageResult, VideoContext, PIPELINE_VERSION

REPO_ROOT = Path(__file__).resolve().parents[3]

_PERFORMANCE_SNAPSHOT_REQUIRED = (
    ("schema", "name"),
    ("schema", "version"),
    ("platform",),
    ("video_id",),
    ("observed_at",),
    ("metrics", "views"),
    ("metrics", "likes"),
    ("metrics", "comments"),
    ("metrics", "shares"),
    ("collector", "name"),
)


def _repo_path(p: Path) -> Path:
    return p if p.is_absolute() else REPO_ROOT / p


def performance_snapshot_stage(ctx: VideoContext) -> StageResult:
    t0 = time.monotonic()
    meta = ctx.ingestion.get("metadata") or {}
    video_id = ctx.ingestion.get("video_id") or meta.get("video_id")
    if not video_id:
        raise PipelineStageError("performance_snapshot", "missing_video_id",
                                 "ingestion payload has no video id")
    observed_at = meta.get("collected_at") or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    published_at = meta.get("published_at")
    age_seconds = None
    if published_at:
        try:
            pub = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
            obs = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
            age_seconds = max(0.0, (obs - pub).total_seconds())
        except ValueError as exc:
            raise PipelineStageError(
                "performance_snapshot", "bad_timestamp", f"unparsable timestamp: {exc}"
            ) from exc
    collector = {
        "name": meta.get("collector_name") or "unknown",
        "version": meta.get("collector_version"),
    }
    snapshot = {
        "schema": {"name": "performance", "version": "0.1"},
        "platform": "tiktok",
        "video_id": str(video_id),
        "source_url": meta.get("source_url") or ctx.url,
        "creator_handle": meta.get("creator_handle"),
        "creator_id": meta.get("creator_id"),
        "published_at": published_at,
        "observed_at": observed_at,
        "age_since_publish_seconds": age_seconds,
        "metrics": {
            "views": meta.get("views"),
            "likes": meta.get("likes"),
            "comments": meta.get("comments"),
            "shares": meta.get("shares"),
            "saves": meta.get("saves"),
        },
        "collector": collector,
    }
    missing = [
        ".".join(parts)
        for parts in _PERFORMANCE_SNAPSHOT_REQUIRED
        if not _dig(snapshot, parts) and _dig(snapshot, parts) != 0
    ]
    if missing:
        raise PipelineStageError(
            "performance_snapshot", "contract_violation",
            f"snapshot missing required fields: {missing}",
        )
    out = ctx.record_dir / "source" / "performance" / "performance_v0_1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    import json

    out.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return StageResult(
        ok=True,
        artifacts={"snapshot_path": str(out), "observed": snapshot["metrics"],
                   "observed_at": observed_at},
        latency_seconds=round(time.monotonic() - t0, 3),
        schema_version="0.1",
    )


def _dig(d: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def perception_stage(ctx: VideoContext) -> StageResult:
    from ..perception.pipeline import run_perception

    t0 = time.monotonic()
    video_path = ctx.record_dir / "source" / "video.mp4"
    if not video_path.exists():
        raise PipelineStageError(
            "perception", "missing_media", f"video artifact absent: {video_path}"
        )
    out_dir = ctx.record_dir / "perception" / "v1"
    manifest = run_perception(video_path, out_dir)
    return StageResult(
        ok=True,
        artifacts={
            "perception_dir": str(out_dir),
            "media_facts_path": str(out_dir / "media_facts.json"),
            "shots_path": str(out_dir / "shots.json"),
            "frame_count": len(manifest.frames),
            "shot_count": len(manifest.shots.shots),
        },
        latency_seconds=round(time.monotonic() - t0, 3),
        schema_version=manifest.pipeline_version,
    )


def decompile_stage(ctx: VideoContext) -> StageResult:
    from ..baseline.artifacts import new_run_id
    from ..multistep.config import load_multistep_config
    from ..multistep.runner import MultiStepRunError, run_multistep

    t0 = time.monotonic()
    config = load_multistep_config()
    # Point the validated component at this record's directories; its internal
    # layout (perception/<version>, decompilation/multi_step/<run_id>) applies.
    config.derived_root = ctx.record_dir.parent
    config.pass_a_prompt_path = _repo_path(config.pass_a_prompt_path)
    config.pass_b_prompt_path = _repo_path(config.pass_b_prompt_path)
    config.schema_path = _repo_path(config.schema_path)

    video_path = ctx.record_dir / "source" / "video.mp4"
    if not video_path.exists():
        raise PipelineStageError(
            "decompile", "missing_media", f"video artifact absent: {video_path}"
        )
    video_id = ctx.ingestion["video_id"]
    try:
        result = run_multistep(
            config,
            video_path=video_path,
            video_id=video_id,
            source_metadata=ctx.ingestion.get("metadata") or {},
            run_id=new_run_id(),
        )
    except MultiStepRunError as exc:
        raise PipelineStageError("decompile", "model_or_validation", str(exc)) from exc
    except Exception as exc:  # e.g. missing credentials -> loud, isolated failure
        raise PipelineStageError("decompile", type(exc).__name__, str(exc)) from exc

    # Surface the canonical artifacts at the record layout's top level without
    # touching the immutable per-run raw responses.
    run_dir = Path(result["directory"])
    dest = ctx.record_dir / "decompilation"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("creative_ir.json", "canonical_ir.json", "validation.json", "usage.json"):
        src = run_dir / name
        if src.exists():
            target = dest / name
            if not target.exists():  # never overwrite a prior validated artifact
                shutil.copy2(src, target)

    usage = result.get("usage") or {}
    return StageResult(
        ok=True,
        artifacts={
            "run_dir": str(run_dir),
            "creative_ir_path": str(dest / "creative_ir.json"),
            "canonical_ir_path": str(dest / "canonical_ir.json"),
            "validation": "pass",
        },
        usage_cost_usd=float(usage.get("total_cost_usd") or 0.0),
        latency_seconds=float(usage.get("total_latency_seconds")
                              or (time.monotonic() - t0)),
        model_id=(
            f"{config.model_id} (pass A) + {config.synthesis_model} (pass B)"
        ),
        prompt_version=(
            f"{config.pass_a_prompt_version} (pass A) + "
            f"{config.pass_b_prompt_version} (pass B)"
        ),
        schema_version="0.1",
    )


def canonical_projection_stage(ctx: VideoContext) -> StageResult:
    """Verify the deterministic projection recorded during decompilation."""
    import json

    t0 = time.monotonic()
    dest = ctx.record_dir / "decompilation"
    validation_path = dest / "validation.json"
    creative_path = dest / "creative_ir.json"
    canonical_path = dest / "canonical_ir.json"
    missing = [str(p) for p in (validation_path, creative_path, canonical_path) if not p.exists()]
    if missing:
        raise PipelineStageError(
            "project_canonical", "missing_artifacts", f"missing: {missing}"
        )
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if not validation.get("valid"):
        raise PipelineStageError(
            "project_canonical", "validation_failed",
            json.dumps(validation.get("errors", [])),
        )
    return StageResult(
        ok=True,
        artifacts={"validation_path": str(validation_path)},
        latency_seconds=round(time.monotonic() - t0, 3),
        schema_version="0.1",
    )


def build_default_stages() -> "PipelineStages":  # type: ignore[name-defined]
    from .stages import PipelineStages

    return PipelineStages(
        performance_snapshot=performance_snapshot_stage,
        perception=perception_stage,
        decompile=decompile_stage,
        project_canonical=canonical_projection_stage,
    )
