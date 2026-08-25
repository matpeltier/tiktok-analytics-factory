"""Deterministic, record-level QA validators.

Every validator takes a DatasetRecord (or its parts) and returns a list of
ValidationIssue. An empty list means the check passed. Validators never raise
on bad data; they report failures as issues with a taxonomy category so that
systematic problems can be counted by the audit.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .records import DatasetRecord, canonical_json
from .taxonomy import ValidationIssue

FRAME_TOLERANCE_S = 0.05

Validator = Callable[[DatasetRecord], list[ValidationIssue]]

_VALIDATOR_REGISTRY: dict[str, Validator] = {}


def register_validator(name: str):
    def deco(fn: Validator) -> Validator:
        _VALIDATOR_REGISTRY[name] = fn
        return fn

    return deco


def run_validators(record: DatasetRecord, names: list[str] | None = None) -> list[ValidationIssue]:
    selected = names or sorted(_VALIDATOR_REGISTRY)
    issues: list[ValidationIssue] = []
    for name in selected:
        issues.extend(_VALIDATOR_REGISTRY[name](record))
    return issues


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts


# --------------------------------------------------------------------------
# Source / provenance
# --------------------------------------------------------------------------


@register_validator("source")
def validate_source(record: DatasetRecord) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    m = record.manifest

    vid = m.get("video_id")
    if not vid:
        issues.append(ValidationIssue("metadata_missing", "manifest has no video_id", "blocking", "video_id"))
    elif vid != record.video_id:
        issues.append(
            ValidationIssue(
                "source_collection",
                f"video_id {vid!r} does not match record path {record.video_id!r}",
                "blocking",
                "video_id",
            )
        )

    if not m.get("source_url"):
        issues.append(ValidationIssue("source_collection", "source_url missing", "material", "source_url"))

    mp4_hash = m.get("mp4_sha256")
    if not mp4_hash:
        issues.append(ValidationIssue("provenance", "mp4_sha256 missing", "material", "mp4_sha256"))
    elif not re.fullmatch(r"[0-9a-f]{64}", str(mp4_hash)):
        issues.append(ValidationIssue("provenance", "mp4_sha256 is not a sha256 hex digest", "material", "mp4_sha256"))

    mp4_path = m.get("mp4_path")
    if mp4_path:
        p = Path(mp4_path)
        if not p.is_absolute():
            # resolve relative to dataset root's parent chain: try record dir,
            # then repo-relative
            candidates = [record.root / mp4_path, record.root.parent.parent / mp4_path]
            p = next((c for c in candidates if c.exists()), candidates[0])
        if not Path(p).exists():
            issues.append(
                ValidationIssue("source_collection", f"local source file missing: {mp4_path}", "material", "mp4_path")
            )

    published_at = _parse_ts(m.get("published_at"))
    observed_at = _parse_ts(m.get("observed_at"))
    if m.get("published_at") is not None and published_at is None:
        issues.append(ValidationIssue("metadata_missing", f"published_at unparseable: {m.get('published_at')!r}", "minor", "published_at"))
    if observed_at is None:
        issues.append(ValidationIssue("metadata_missing", "observed_at missing or unparseable", "minor", "observed_at"))
    if published_at and observed_at and observed_at < published_at:
        issues.append(
            ValidationIssue("metadata_missing", "observed_at is earlier than published_at", "material", "observed_at")
        )

    cohort = load_cohort_config(record.root)
    if cohort is not None:
        for key in ("cohort_id", "cohort_version"):
            expected = cohort.get(key)
            actual = m.get(key)
            if expected is None:
                continue
            if actual != expected:
                issues.append(
                    ValidationIssue(
                        "cohort_mismatch",
                        f"{key} {actual!r} does not match approved config {expected!r}",
                        "blocking",
                        key,
                    )
                )
    else:
        if m.get("cohort_id") is None:
            issues.append(ValidationIssue("cohort_mismatch", "cohort_id missing from manifest and no approved cohort config found", "material", "cohort_id"))
    return issues


def load_cohort_config(record_root: Path) -> dict[str, Any] | None:
    """Look for the approved cohort config walking up from the record directory."""
    for parent in [record_root, *record_root.parents]:
        candidate = parent / "cohort.json"
        if candidate.is_file():
            import json

            with open(candidate, encoding="utf-8") as fh:
                return json.load(fh)
        if parent.name == "data":
            break
    return None


# --------------------------------------------------------------------------
# Perception
# --------------------------------------------------------------------------


@register_validator("perception")
def validate_perception(record: DatasetRecord) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    p = record.perception
    if p is None:
        issues.append(ValidationIssue("media_probe", "perception.json missing", "material"))
        return issues

    media = p.get("media") if isinstance(p, dict) else None
    if not isinstance(media, dict):
        issues.append(ValidationIssue("media_probe", "perception.media facts missing", "material"))
        return issues

    duration = media.get("duration_s")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        issues.append(ValidationIssue("media_probe", f"invalid duration: {duration!r}", "material", "duration_s"))

    for key in ("width", "height", "fps"):
        val = media.get(key)
        if not isinstance(val, (int, float)) or isinstance(val, bool) or val <= 0:
            issues.append(ValidationIssue("media_probe", f"invalid {key}: {val!r}", "material", key))

    shots = p.get("shots")
    if not isinstance(shots, list) or not shots:
        issues.append(ValidationIssue("shot_boundary", "no shots present", "material"))
        return issues

    prev_end = -1.0
    for i, shot in enumerate(shots):
        sid = shot.get("shot_id")
        start = shot.get("start_s")
        end = shot.get("end_s")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            issues.append(ValidationIssue("shot_boundary", f"shot {i} ({sid}) has non-numeric bounds", "material", shot_id=sid))
            continue
        if end <= start:
            issues.append(ValidationIssue("shot_boundary", f"shot {i} ({sid}) end <= start", "material", shot_id=sid))
        if start < prev_end - 1e-9:
            issues.append(ValidationIssue("shot_boundary", f"shot {i} ({sid}) overlaps previous shot", "material", shot_id=sid))
        if i > 0 and abs(start - prev_end) > FRAME_TOLERANCE_S:
            issues.append(
                ValidationIssue("shot_boundary", f"gap between shot {i-1} and shot {i} ({sid})", "minor", shot_id=sid)
            )
        frame = shot.get("representative_frame")
        if not frame:
            issues.append(ValidationIssue("shot_boundary", f"shot {i} ({sid}) missing representative_frame", "minor", shot_id=sid))
        elif not (record.root / str(frame)).exists() and not Path(str(frame)).exists():
            issues.append(
                ValidationIssue(
                    "shot_boundary",
                    f"representative frame file missing for shot {sid}: {frame}",
                    "minor",
                    shot_id=sid,
                )
            )
        prev_end = max(prev_end, end)

    first_start = shots[0].get("start_s")
    if isinstance(first_start, (int, float)) and abs(first_start) > FRAME_TOLERANCE_S:
        issues.append(ValidationIssue("shot_boundary", f"first shot starts at {first_start}, expected ~0", "minor"))
    last_end = shots[-1].get("end_s")
    if (
        isinstance(last_end, (int, float))
        and isinstance(duration, (int, float))
        and abs(last_end - duration) > FRAME_TOLERANCE_S
    ):
        issues.append(
            ValidationIssue("shot_boundary", f"last shot ends at {last_end}, media duration is {duration}", "minor")
        )
    return issues


# --------------------------------------------------------------------------
# CreativeIR
# --------------------------------------------------------------------------

REQUIRED_CREATIVE_PROVENANCE = ("schema_version", "pipeline_version", "prompt_version", "model_id")


@register_validator("creative_ir")
def validate_creative_ir(record: DatasetRecord) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    ir = record.creative_ir
    if ir is None:
        issues.append(ValidationIssue("schema_validation", "creative_ir.json missing", "material"))
        return issues

    for key in REQUIRED_CREATIVE_PROVENANCE:
        if not ir.get(key):
            issues.append(ValidationIssue("provenance", f"CreativeIR missing {key}", "material", key))

    src = ir.get("source_video_id")
    if src != record.video_id:
        issues.append(
            ValidationIssue("schema_validation", f"CreativeIR source reference {src!r} != video id {record.video_id!r}", "blocking")
        )

    shots = ir.get("shots")
    if not isinstance(shots, list) or not shots:
        issues.append(ValidationIssue("schema_validation", "CreativeIR has no shots list", "material"))
        return issues

    seen_ids: set[str] = set()
    observed_shot_ids: set[str] = set()
    observed_text_ids: set[str] = set()

    for i, shot in enumerate(shots):
        sid = shot.get("shot_id")
        if not sid:
            issues.append(ValidationIssue("schema_validation", f"CreativeIR shot {i} missing shot_id", "material"))
        elif sid in seen_ids:
            issues.append(ValidationIssue("schema_validation", f"duplicate CreativeIR shot_id: {sid}", "material", shot_id=sid))
        else:
            seen_ids.add(sid)
            observed_shot_ids.add(sid)

        tr = shot.get("time_range") or shot.get("timeline")
        if tr is not None:
            start, end = tr.get("start_s"), tr.get("end_s")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
                issues.append(ValidationIssue("schema_validation", f"shot {sid}: invalid time range", "material", shot_id=sid))

        for text in shot.get("text_overlays", []) or []:
            tid = text.get("text_id")
            if tid:
                observed_text_ids.add(tid)
        for line in shot.get("spoken_dialogue", []) or []:
            did = line.get("line_id")
            if did:
                observed_text_ids.add(did)

        for kind in ("visual_description", "hook", "narrative_role", "commercial_reasoning"):
            node = shot.get(kind)
            if isinstance(node, dict):
                for ref in node.get("inferred_from", []) or []:
                    ref_id = ref.get("id") if isinstance(ref, dict) else ref
                    if ref_id and ref_id not in observed_shot_ids and ref_id not in observed_text_ids:
                        issues.append(
                            ValidationIssue(
                                "schema_validation",
                                f"{kind} on shot {sid} references unknown id {ref_id!r}",
                                "material",
                                shot_id=sid,
                            )
                        )

    if isinstance(ir.get("generation"), (str, dict)):
        gen = ir["generation"]
        prose = gen if isinstance(gen, str) else canonical_json(gen)
        if prose.strip():
            issues.append(
                ValidationIssue("reconstruction", "CreativeIR contains 'generation' content; generation belongs outside creative features", "blocking", "generation")
            )
    return issues


# --------------------------------------------------------------------------
# CanonicalIR
# --------------------------------------------------------------------------


@register_validator("canonical_ir")
def validate_canonical_ir(record: DatasetRecord) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    can = record.canonical_ir
    if can is None:
        issues.append(ValidationIssue("canonical_projection", "canonical_ir.json missing", "material"))
        return issues

    if record.creative_ir is not None and can.get("source_video_id") != record.creative_ir.get("source_video_id"):
        issues.append(
            ValidationIssue(
                "canonical_projection",
                f"CanonicalIR source {can.get('source_video_id')!r} != CreativeIR source "
                f"{record.creative_ir.get('source_video_id')!r}",
                "blocking",
            )
        )

    from .projection import project_canonical

    projected = project_canonical(record.creative_ir) if record.creative_ir is not None else None
    stored_projection = can.get("projection")
    if projected is not None:
        if stored_projection is None:
            issues.append(ValidationIssue("canonical_projection", "CanonicalIR has no projection payload", "material"))
        elif canonical_json(stored_projection) != canonical_json(projected):
            issues.append(
                ValidationIssue(
                    "canonical_projection",
                    "stored CanonicalIR projection does not match deterministic projection of current CreativeIR",
                    "material",
                )
            )

    blob = canonical_json(can).lower()
    for marker in ("\"generation\"", "generation_notes"):
        if marker in blob:
            issues.append(ValidationIssue("canonical_projection", f"CanonicalIR contains generation field: {marker}", "blocking"))
            break

    perf_markers = ("play_count", "digg_count", "share_count", "comment_count", "view_count", "likes", "views")
    creative_blob = canonical_json(can.get("projection", {})).lower()
    leaked = [m for m in perf_markers if f'"{m}"' in creative_blob]
    if leaked:
        issues.append(
            ValidationIssue(
                "canonical_projection",
                f"raw performance metrics leaked into CanonicalIR creative fields: {leaked}",
                "blocking",
            )
        )
    return issues


# --------------------------------------------------------------------------
# Performance
# --------------------------------------------------------------------------


@register_validator("performance")
def validate_performance(record: DatasetRecord) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    perf = record.performance
    if perf is None:
        issues.append(ValidationIssue("performance_snapshot", "performance.json missing", "material"))
        return issues

    snapshots = perf.get("snapshots", [perf] if perf else [])
    if not snapshots:
        issues.append(ValidationIssue("performance_snapshot", "no performance snapshots", "material"))
        return issues

    prev_ts: datetime | None = None
    for i, snap in enumerate(snapshots):
        metrics = snap.get("metrics", {})
        for key, val in metrics.items():
            if val is None:
                continue  # null == unknown by convention
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                issues.append(ValidationIssue("performance_snapshot", f"metric {key!r} is not numeric: {val!r}", "material", key))
            elif val < 0:
                issues.append(ValidationIssue("performance_snapshot", f"negative metric value {key}={val}", "material", key))

        ts = _parse_ts(snap.get("observed_at"))
        if ts is None:
            issues.append(ValidationIssue("performance_snapshot", f"snapshot {i} missing/unparseable observed_at", "material"))
        elif prev_ts is not None and ts < prev_ts:
            issues.append(ValidationIssue("performance_snapshot", f"snapshots are not timestamp-ordered at index {i}", "material"))
        prev_ts = ts or prev_ts

        pub = _parse_ts(record.manifest.get("published_at"))
        if ts and pub and ts < pub:
            issues.append(ValidationIssue("performance_snapshot", "snapshot observed before video was published", "material"))
        if ts and metrics and not any(v is not None for v in metrics.values()):
            pass  # all-unknown handled per-metric above
    return issues


# --------------------------------------------------------------------------
# Extension point for later target validators (#9)
# --------------------------------------------------------------------------


def register_target_validator(fn: Validator) -> Validator:
    """Register a derived-target validator without making QA depend on #9."""
    _VALIDATOR_REGISTRY.setdefault("derived_target", fn)
    return fn
