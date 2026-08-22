"""Deterministic projection from a validated CreativeIR v0.1 to CanonicalIR v0.1.

Rules:
- Pure function of the CreativeIR payload: same input -> same output.
- No model calls.
- Input must validate against the CreativeIR schema first; failures raise
  ProjectionError (fail loudly, no silent fallbacks).
- Fields not represented in CanonicalIR are deliberately dropped, never
  serialized into an ``extra`` blob.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "schemas"

with (SCHEMAS_DIR / "creative_ir_v0_1.json").open() as _f:
    CREATIVE_IR_SCHEMA = json.load(_f)
with (SCHEMAS_DIR / "canonical_ir_v0_1.json").open() as _f:
    CANONICAL_IR_SCHEMA = json.load(_f)

try:
    import jsonschema
except ImportError as exc:  # pragma: no cover
    raise ImportError("jsonschema is required for contract validation") from exc


class ProjectionError(ValueError):
    """Raised when CreativeIR input is invalid or cannot be projected."""


def validate_against_schema(instance: dict[str, Any], schema: dict[str, Any]) -> None:
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    errors = sorted(validator_cls(schema).iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        detail = "; ".join(
            f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors[:5]
        )
        raise ProjectionError(f"schema validation failed ({len(errors)} error(s)): {detail}")


def project_creative_to_canonical(
    creative_ir: dict[str, Any], *, projected_at: str
) -> dict[str, Any]:
    """Project a validated CreativeIR into CanonicalIR deterministically."""
    validate_against_schema(creative_ir, CREATIVE_IR_SCHEMA)

    for idx, shot in enumerate(creative_ir["observed"].get("shots", [])):
        if not shot["end_seconds"] > shot["start_seconds"]:
            raise ProjectionError(
                f"shot ordering invalid: {shot['shot_id']} end_seconds "
                f"({shot['end_seconds']}) <= start_seconds ({shot['start_seconds']})"
            )
        if (
            idx > 0
            and shot["start_seconds"]
            < creative_ir["observed"]["shots"][idx - 1]["start_seconds"]
        ):
            raise ProjectionError(
                f"shot ordering invalid: {shot['shot_id']} starts before its predecessor"
            )

    source = creative_ir["source"]
    observed = creative_ir["observed"]
    inferred = creative_ir["inferred"]
    shots = observed.get("shots", [])

    durations = [round(s["end_seconds"] - s["start_seconds"], 6) for s in shots]

    subject_categories: list[str] = []
    camera_motions: list[str] = []
    transitions: list[str] = []
    audio_categories: list[str] = []
    has_text = False
    text_roles: set[str] = set()
    has_dialogue = False

    for shot in shots:
        for sa in shot.get("subjects_and_actions", []):
            cat = sa.get("subject_category")
            if cat and cat not in ("unknown",):
                if cat not in subject_categories:
                    subject_categories.append(cat)
        motion = shot.get("camera_movement")
        if motion and motion != "unknown" and motion not in camera_motions:
            camera_motions.append(motion)
        transition = shot.get("editing_transition_in")
        if transition and transition not in ("none", "unknown") and transition not in transitions:
            transitions.append(transition)
        if shot.get("on_screen_text"):
            has_text = True
            if any(t.get("certainty") == "exact" and (t.get("start_seconds") or 0.0) <= 3.0 for t in shot["on_screen_text"]):
                text_roles.add("hook_text")
        for t in shot.get("on_screen_text", []):
            if any(k in t["text"].lower() for k in ("link in bio", "follow", "comment", "shop")):
                text_roles.add("cta")
        if shot.get("spoken_dialogue"):
            has_dialogue = True
        for audio in shot.get("audio", []):
            cat = audio.get("category")
            if cat and cat not in ("unknown",) and cat not in audio_categories:
                audio_categories.append(cat)

    on_screen_text_role: str | None = None
    if text_roles:
        on_screen_text_role = "cta" if "cta" in text_roles else "hook_text"
    elif has_text:
        on_screen_text_role = "caption_subtitle"
    else:
        on_screen_text_role = "none_observed"

    hook = inferred.get("hook")
    commercial = inferred.get("commercial_interpretation") or {}

    canonical_inferred: dict[str, Any] = {
        "commercial_status": commercial.get("status", "uncertain"),
        "hook_type": (hook or {}).get("type"),
        "narrative_structure": ((inferred.get("narrative_structure") or {}).get("structure")),
        "attention_mechanism_labels": [
            m.get("category") or m["mechanism"] for m in inferred.get("attention_mechanisms", [])
        ],
        "persuasion_mechanism_labels": [
            m.get("category") or m["mechanism"]
            for m in inferred.get("marketing_persuasion_mechanisms", [])
        ],
        "proof_type": commercial.get("proof_type"),
        "trust_signal_count": len(commercial.get("trust_signals", []) or []),
        "objection_count": len(commercial.get("objections_addressed", []) or []),
        "cta_type": commercial.get("cta_type"),
        "overall_confidence": (inferred.get("overall_concept") or {}).get("confidence"),
    }

    canonical: dict[str, Any] = {
        "schema_version": "0.1",
        "platform": source["platform"],
        "video_id": source["video_id"],
        "source_url": source.get("source_url"),
        "created_at_source": source.get("published_at"),
        "projected_at": projected_at,
        "projection_source": {
            "creative_ir_schema_version": creative_ir["decompilation"]["schema_version"],
            "decompilation_pipeline_version": creative_ir["decompilation"]["pipeline_version"],
        },
        "duration_seconds": source.get("duration_seconds"),
        "observed": {
            "shot_count": len(shots),
            "shot_duration_mean_seconds": round(statistics.fmean(durations), 6) if durations else None,
            "shot_duration_min_seconds": min(durations) if durations else None,
            "shot_duration_max_seconds": max(durations) if durations else None,
            "subject_categories": subject_categories,
            "has_on_screen_text": has_text,
            "on_screen_text_role": on_screen_text_role,
            "has_spoken_dialogue": has_dialogue,
            "camera_motion_categories": camera_motions,
            "transition_categories": transitions,
            "audio_categories": audio_categories,
            "hook_start_seconds": (observed.get("hook_evidence") or {}).get("start_seconds"),
            "first_product_appearance_seconds": commercial.get("first_product_appearance_seconds"),
        },
        "inferred": canonical_inferred,
    }

    validate_against_schema(canonical, CANONICAL_IR_SCHEMA)
    return canonical
