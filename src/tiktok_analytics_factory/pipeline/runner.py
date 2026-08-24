"""Batch pilot runner: cohort filter -> per-video pipeline -> index -> report.

Failure isolation: each source is processed independently; a failure in one
video produces an explicit per-video status and never aborts the batch.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..ingestion.ingest import ingest
from ..ingestion.models import NormalizedMetadata
from .cohort import CohortDecision, CohortPolicy
from .index import build_index
from .record import (
    build_manifest,
    build_record_dir,
    persist_rejection,
    write_json,
)
from .report import aggregate
from .retry import RetryPolicy, run_with_retry
from .stages import (
    PIPELINE_VERSION,
    PipelineStageError,
    PipelineStages,
    StageResult,
    VideoContext,
)

logger = logging.getLogger(__name__)


@dataclass
class PilotOptions:
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    resume: bool = True  # skip already-successful records unless reprocessing
    reprocess: bool = False


@dataclass
class PilotSummary:
    requested: int
    rows: list[dict[str, Any]]
    metrics: dict[str, Any]
    decision: str
    blockers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "processed": len(self.rows),
            "metrics": self.metrics,
            "gate_decision": self.decision,
            "gate_blockers": self.blockers,
        }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _status_for_stage(stage: str) -> str:
    return {
        "performance_snapshot": "ingestion_failed",
        "perception": "perception_failed",
        "decompile": "decompilation_failed",
        "project_canonical": "validation_failed",
    }.get(stage, f"{stage}_failed")


def _process_one(
    entry: Any,
    policy: CohortPolicy,
    stages: PipelineStages,
    output_root: Path,
    options: PilotOptions,
) -> dict[str, Any]:
    """Run the full validated pipeline for one candidate source."""
    decision: CohortDecision = policy.check(entry)
    if not decision.accepted:
        persist_rejection(output_root, entry, decision.reason, policy.cohort_id, policy.version)
        return {"url": entry.url, "video_id": entry.video_id, "status": "rejected_by_cohort",
                "failure_category": None}

    # Ingestion (validated component from issue #2), with bounded retry for
    # transient collection errors only.
    record_dir: Path | None = None
    ingest_payload: dict[str, Any] = {}
    try:
        outcome = run_with_retry(
            lambda: ingest(entry.url, str(output_root / "raw")),
            options.retry_policy,
        )
        if not outcome.succeeded or outcome.value is None:
            raise RuntimeError("; ".join(outcome.errors))
        result = outcome.value
        video_id: str = result.video_id
        record_dir = build_record_dir(output_root, video_id)
        metadata = NormalizedMetadata(**result.metadata.to_json_dict())
        ingest_payload = {
            "video_id": video_id,
            "metadata": metadata.to_json_dict(),
            "artifact_dir": str(result.artifact_dir),
        }
        # Link/copy immutable raw artifacts into the record (never overwrite).
        raw_dir = Path(result.artifact_dir)
        src_video = raw_dir / "video.mp4"
        if src_video.exists():
            dst = record_dir / "source" / "video.mp4"
            if not dst.exists():
                shutil.copy2(src_video, dst)
        for name in ("manifest.json", "metadata.raw.json"):
            src = raw_dir / name
            if src.exists() and not (record_dir / "source" / name).exists():
                shutil.copy2(src, record_dir / "source" / name)
        write_json(record_dir / "source" / "metadata.normalized.json", metadata.to_json_dict())
    except Exception as exc:  # noqa: BLE001 - failure isolation must catch everything per video
        vid = getattr(exc, "payload", {}).get("video_id", None) if hasattr(exc, "payload") else entry.video_id
        logger.error("ingestion failed for %s: %s", entry.url, exc)
        if record_dir is not None:
            manifest = build_manifest(
                entry=entry_with_id(entry, vid),
                cohort_id=policy.cohort_id,
                cohort_version=policy.version,
                status="ingestion_failed",
                stage_results={},
                pipeline_version=PIPELINE_VERSION,
                source_hash=None,
                video_hash=None,
                failure={"stage": "ingestion", "category": type(exc).__name__, "message": str(exc)},
            )
            write_json(record_dir / "record_manifest.json", manifest)
        return {"url": entry.url, "video_id": vid, "status": "ingestion_failed",
                "failure_category": "collection"}

    ctx = VideoContext(
        url=entry.url,
        video_id=ingest_payload["video_id"],
        cohort_id=policy.cohort_id,
        cohort_version=policy.version,
        record_dir=record_dir,
        ingestion=ingest_payload,
    )

    stage_results: dict[str, StageResult] = {}
    ordered = [
        ("performance_snapshot", stages.performance_snapshot),
        ("perception", stages.perception),
        ("decompile", stages.decompile),
        ("project_canonical", stages.project_canonical),
    ]
    status = "success"
    failure: dict[str, str] | None = None
    for name, fn in ordered:
        try:
            res = fn(ctx)
        except PipelineStageError as exc:
            res = StageResult(ok=False, error_category=exc.category, error_message=exc.message)
        except Exception as exc:  # noqa: BLE001 - failure isolation must catch everything per video
            res = StageResult(ok=False, error_category="unexpected", error_message=str(exc))
        stage_results[name] = res
        if not res.ok:
            status = _status_for_stage(name)
            failure = {
                "stage": name,
                "category": res.error_category or "unknown",
                "message": res.error_message or "",
            }
            break

    video_hash = None
    src_video = record_dir / "source" / "video.mp4"
    if src_video.exists():
        video_hash = _sha256_file(src_video)

    perf = stage_results.get("performance_snapshot")
    manifest = build_manifest(
        entry=entry_with_id(entry, ctx.video_id),
        cohort_id=policy.cohort_id,
        cohort_version=policy.version,
        status=status,
        stage_results=stage_results,
        pipeline_version=PIPELINE_VERSION,
        source_hash=None,
        video_hash=video_hash,
        failure=failure,
    )
    manifest["ingestion_status"] = "ok"
    manifest["perception_status"] = (
        "ok" if stage_results.get("perception") and stage_results["perception"].ok else
        ("failed" if "perception" in stage_results else "not_run")
    )
    manifest["decompilation_status"] = (
        "ok" if stage_results.get("decompile") and stage_results["decompile"].ok else
        ("failed" if "decompile" in stage_results else "not_run")
    )
    manifest["creative_ir_path"] = str(
        (record_dir / "decompilation" / "creative_ir.json").relative_to(output_root)
    ) if status == "success" else None
    manifest["canonical_ir_path"] = str(
        (record_dir / "decompilation" / "canonical_ir.json").relative_to(output_root)
    ) if status == "success" else None
    manifest["schema_valid"] = status == "success"
    manifest["source"] = {
        "creator_id": (ingest_payload.get("metadata", {}) or {}).get("creator_id"),
        "creator_handle": (ingest_payload.get("metadata", {}) or {}).get("creator_handle"),
        "published_at": (ingest_payload.get("metadata", {}) or {}).get("published_at"),
        "duration_seconds": (ingest_payload.get("metadata", {}) or {}).get("duration_seconds"),
    }
    observed = (perf.artifacts if perf else {}).get("observed", {})
    manifest["performance_snapshot_observed"] = {
        "observed_at": observed.get("observed_at"),
        "views": observed.get("views"),
        "likes": observed.get("likes"),
        "comments": observed.get("comments"),
        "shares": observed.get("shares"),
    }
    write_json(record_dir / "record_manifest.json", manifest)

    cat = failure["category"] if failure else None
    return {"url": entry.url, "video_id": ctx.video_id, "status": status,
            "failure_category": cat}


def entry_with_id(entry: Any, video_id: str | None):
    """Return a shallow copy of the entry with a resolved video ID if missing."""
    import dataclasses

    if video_id and not entry.video_id:
        return dataclasses.replace(entry, video_id=video_id)
    return entry


def run_pilot(
    cohort_path: str | Path,
    sources_path: str | Path,
    output_root: str | Path,
    stages: PipelineStages | None = None,
    options: PilotOptions | None = None,
    reviews_path: str | Path | None = None,
) -> PilotSummary:
    from .cohort import load_cohort
    from .sources import load_sources

    options = options or PilotOptions()
    policy = load_cohort(cohort_path)
    entries = load_sources(sources_path)
    if len(entries) > policy.max_videos:
        raise ValueError(
            f"source list has {len(entries)} entries; pilot hard max is {policy.max_videos}"
        )
    out = Path(output_root)
    out.mkdir(parents=True, exist_ok=True)

    if stages is None:
        # Wire the validated components (#2/#3/#5/#6). Any missing dependency
        # or credential fails loudly per video; it never fakes success.
        from .adapters import build_default_stages

        stages = build_default_stages()

    rows: list[dict[str, Any]] = []
    for entry in entries:
        # Resumable rerun: skip records that already succeeded.
        if options.resume and not options.reprocess and entry.video_id:
            existing = out / "records" / entry.video_id / "record_manifest.json"
            if existing.exists():
                prev = json.loads(existing.read_text(encoding="utf-8"))
                if prev.get("status") == "success":
                    logger.info("skipping already-successful %s", entry.video_id)
                    rows.append({"url": entry.url, "video_id": entry.video_id,
                                 "status": "success", "failure_category": None,
                                 "skipped_resumed": True})
                    continue
        rows.append(_process_one(entry, policy, stages, out, options))

    records_root = out / "records"
    index_rows = build_index(records_root, out / "index.parquet")
    metrics = aggregate(index_rows, requested=len(entries))
    if reviews_path is not None:
        rp = Path(reviews_path)
        if not rp.exists():
            raise FileNotFoundError(f"reviews file not found: {rp}")
        reviews = [
            json.loads(line)
            for line in rp.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        from .report import apply_manual_review
        metrics = apply_manual_review(metrics, reviews)
        write_json(out / "manual_review.json", metrics["manual_review"])
    decision, blockers = _decide(metrics)
    from .report import write_report
    write_report(out / "pilot_report.json", metrics, decision, blockers)
    return PilotSummary(len(entries), rows, metrics, decision, blockers)


def _decide(metrics: dict[str, Any]) -> tuple[str, list[str]]:
    from .report import decide_gate
    return decide_gate(metrics)
