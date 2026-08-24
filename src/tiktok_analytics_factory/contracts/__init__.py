"""Contract validation and deterministic CreativeIR -> CanonicalIR projection.

JSON Schema (Draft 2020-12) files under ``schemas/`` are the persisted
contracts. This module provides:

- schema loading and validation helpers (fail loudly on invalid input);
- :func:`project_creative_to_canonical`, a pure, deterministic projection
  from a validated CreativeIR dict to a CanonicalIR dict.

No model calls happen here; the projection only reads structured fields.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = _REPO_ROOT / "schemas"

try:
    import jsonschema
except ImportError as exc:  # pragma: no cover - dependency guard
    raise ImportError(
        "jsonschema is required for contract validation. "
        "Install with: pip install 'tiktok-analytics-factory[dev]'"
    ) from exc


class ContractValidationError(ValueError):
    """Raised when an artifact fails its JSON Schema contract."""


@cache
def load_schema(name: str) -> dict[str, Any]:
    path = SCHEMAS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Unknown schema: {name}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def validator_for(name: str) -> jsonschema.protocols.Validator:
    schema = load_schema(name)
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema, format_checker=jsonschema.FormatChecker())


def _semantic_errors(instance: dict[str, Any], schema_name: str) -> list[str]:
    """Cross-field rules JSON Schema cannot express."""
    errors: list[str] = []
    if schema_name == "creative_ir_v0_1":
        prev_end = 0.0
        for shot in instance.get("observed", {}).get("shots", []):
            start = shot["start_seconds"]
            end = shot["end_seconds"]
            if end <= start:
                errors.append(
                    f"shot {shot['shot_id']}: end_seconds ({end}) must be > start_seconds ({start})"
                )
            if start < prev_end:
                errors.append(
                    f"shot {shot['shot_id']}: starts ({start}) before previous shot ends ({prev_end})"
                )
            if start < 0:
                errors.append(f"shot {shot['shot_id']}: negative start_seconds")
            prev_end = max(prev_end, end)
        hook = instance.get("observed", {}).get("hook") or {}
        hs, he = hook.get("start_seconds"), hook.get("end_seconds")
        if hs is not None and he is not None and he <= hs:
            errors.append("hook end_seconds must be > start_seconds")
    if schema_name == "performance_v0_1" and instance.get("age_since_publish_seconds") is not None:
        if instance.get("published_at"):
            published = datetime.fromisoformat(instance["published_at"])
            obs = datetime.fromisoformat(instance["observed_at"])
            expected = (obs - published).total_seconds()
            if abs(expected - float(instance["age_since_publish_seconds"])) > 1.0:
                errors.append(
                    f"age_since_publish_seconds {instance['age_since_publish_seconds']} "
                    f"inconsistent with timestamps (expected {expected})"
                )
    return errors


def validate(instance: dict[str, Any], schema_name: str) -> None:
    """Validate ``instance`` against the named schema plus semantic rules.

    Raises on any error; never mutates ``instance``.
    """
    errors = sorted(
        validator_for(schema_name).iter_errors(instance),
        key=lambda e: list(e.absolute_path),
    )
    messages = [
        f"{schema_name} validation failed at {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in errors
    ]
    messages.extend(f"{schema_name} semantic error: {msg}" for msg in _semantic_errors(instance, schema_name))
    if messages:
        raise ContractValidationError(messages[0])


# --------------------------------------------------------------------------
# Deterministic CreativeIR -> CanonicalIR projection
# --------------------------------------------------------------------------

_SUBJECT_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("hand", "person", "face", "creator", "man", "woman"), "person_creator"),
    (("bread", "dough", "loaf", "loaves", "crumb", "food"), "food"),
    (("oven", "kitchen", "counter", "room", "stove"), "environment"),
    (("product", "bottle", "box", "packaging"), "product"),
)

_PROMO_TEXT_KEYWORDS = ("link", "shop", "buy", "%", "off", "code", "bio")


def _classify_subject(subject: str) -> str | None:
    lowered = subject.lower()
    for keywords, category in _SUBJECT_RULES:
        if any(keyword in lowered for keyword in keywords):
            return category
    return None


def _text_role(text: str) -> str:
    lowered = text.lower()
    if any(keyword in lowered for keyword in _PROMO_TEXT_KEYWORDS):
        return "promotional"
    return "instructional"


def _presence(certs: list[str]) -> bool | None:
    """Collapse per-shot certainty values into one tri-state presence."""
    if "observed" in certs:
        return True
    if all(cert == "absent" for cert in certs):
        return False
    if not certs or "unknown" in certs or "uncertain" in certs:
        return None
    return None


def project_creative_to_canonical(creative_ir: dict[str, Any]) -> dict[str, Any]:
    """Project a validated CreativeIR into CanonicalIR deterministically.

    Raises :class:`ContractValidationError` if the input is not valid
    CreativeIR v0.1. The same input always yields the same output; no model
    call is involved. Fields not representable in CanonicalIR are dropped.
    """
    validate(creative_ir, "creative_ir_v0_1")

    source = creative_ir["source"]
    decompilation = creative_ir["decompilation"]
    observed = creative_ir["observed"]
    inferred = creative_ir["inferred"]
    shots = observed["shots"]

    durations = [s["end_seconds"] - s["start_seconds"] for s in shots]

    subject_categories: list[str] = []
    for shot in shots:
        for subject in shot.get("subjects", []):
            category = _classify_subject(subject)
            if category and category not in subject_categories:
                subject_categories.append(category)
    if not any(s.get("subjects") for s in shots):
        subject_categories.append("none_visible")

    commercial_status = inferred["commercial"]["status"]
    details = inferred["commercial"].get("details")
    is_commercial = commercial_status == "commercial"

    product_present: bool | None = None
    first_product_seconds: float | None = None
    cta_type: str | None = None  # str, None, or "not_applicable"
    proof_labels: list[str] = []
    trust_labels: list[str] = []

    if is_commercial and details:
        product_present = details.get("product_presence") is not None
        first_product_seconds = details.get("first_product_appearance_seconds")
        cta = details.get("cta")
        cta_type = cta["type"] if cta else None
        proof_type = details.get("proof_type")
        proof_labels = [proof_type] if isinstance(proof_type, str) and proof_type != "unknown" else []
        trust_labels = list(details.get("trust_signals") or [])
    elif commercial_status == "non_commercial":
        product_present = False
        cta_type = "not_applicable"
    # uncertain: leave product_present / cta_type as null (unknown)

    visible_text = [
        t for s in shots for t in s.get("on_screen_text", [])
    ]
    spoken = [line for s in shots for line in s.get("spoken_dialogue", [])]
    roles: list[str] = []
    for t in visible_text:
        role = _text_role(t["text"])
        if role not in roles:
            roles.append(role)

    camera_motions: list[str] = []
    transitions: list[str] = []
    music_certs: list[str] = []
    sfx_certs: list[str] = []
    for shot in shots:
        motion = shot.get("camera_movement")
        if isinstance(motion, str) and motion != "unknown" and motion not in camera_motions:
            camera_motions.append(motion)
        transition = shot.get("transition_in")
        if isinstance(transition, str) and transition != "unknown" and transition not in transitions:
            transitions.append(transition)
        audio = shot.get("audio") or {}
        if audio.get("music_certainty"):
            music_certs.append(audio["music_certainty"])
        if audio.get("sfx_certainty"):
            sfx_certs.append(audio["sfx_certainty"])

    hook = observed.get("hook") or {}
    hook_present: bool | None
    if hook.get("description"):
        hook_present = True
    elif hook.get("evidence"):
        hook_present = None  # evidence exists but no grounded description
    else:
        hook_present = False

    hook_type_block = inferred.get("hook_type") or {}
    hook_type_value = hook_type_block.get("value")

    narrative_block = inferred.get("narrative_structure") or {}
    narrative_value = narrative_block.get("value")

    canonical: dict[str, Any] = {
        "schema": {"name": "canonical_ir", "version": "0.1"},
        "source": {
            "platform": source["platform"],
            "video_id": source["video_id"],
            "source_url": source.get("source_url"),
        },
        "decompilation_ref": {
            "pipeline_version": decompilation["pipeline_version"],
            "prompt_version": decompilation["prompt_version"],
            "annotation_mode": decompilation["annotation_mode"],
        },
        "features": {
            "hook_present": hook_present,
            "hook_type": hook_type_value,
            "hook_end_seconds": hook.get("end_seconds"),
            "shot_count": len(shots),
            "shot_duration_min_seconds": min(durations),
            "shot_duration_max_seconds": max(durations),
            "shot_duration_mean_seconds": sum(durations) / len(durations),
            "subject_categories": subject_categories,
            "commercial_status": commercial_status,
            "product_present": product_present,
            "first_product_appearance_seconds": first_product_seconds,
            "visible_text_present": bool(visible_text),
            "visible_text_roles": roles,
            "spoken_dialogue_present": bool(spoken),
            "camera_motion_categories": camera_motions,
            "transition_categories": transitions,
            "music_present": _presence(music_certs),
            "sfx_present": _presence(sfx_certs),
            "narrative_structure": narrative_value,
            "attention_mechanism_labels": sorted(
                {m["label"] for m in inferred.get("attention_mechanisms", [])}
            ),
            "cta_type": cta_type,
            "proof_labels": proof_labels,
            "trust_labels": trust_labels,
            "persuasion_labels": sorted(
                {m["label"] for m in inferred.get("persuasion_mechanisms", [])}
            ),
        },
    }

    validate(canonical, "canonical_ir_v0_1")
    return canonical


# --------------------------------------------------------------------------
# Performance helpers
# --------------------------------------------------------------------------


def build_performance_snapshot(
    *,
    video_id: str,
    source_url: str | None,
    creator_handle: str | None,
    creator_id: str | None,
    published_at: str | None,
    observed_at: str,
    metrics: dict[str, int | None],
    follower_count_at_observation: int | None,
    collector: dict[str, Any],
    notes: str | None = None,
) -> dict[str, Any]:
    """Build and validate a Performance v0.1 snapshot.

    ``metrics`` keys map to views/likes/comments/shares/saves; missing keys
    are recorded as ``null`` (unknown), never zero. When both timestamps are
    present, ``age_since_publish_seconds`` is derived and cross-checked so it
    cannot contradict them.
    """
    metric_keys = ("views", "likes", "comments", "shares", "saves")
    normalized_metrics = {key: metrics.get(key) for key in metric_keys}

    age_since_publish_seconds: float | None = None
    if published_at is not None:
        published = datetime.fromisoformat(published_at)
        obs = datetime.fromisoformat(observed_at)
        delta = (obs - published).total_seconds()
        if delta < 0:
            raise ContractValidationError(
                f"observed_at {observed_at} precedes published_at {published_at}"
            )
        age_since_publish_seconds = delta

    snapshot: dict[str, Any] = {
        "schema": {"name": "performance", "version": "0.1"},
        "platform": "tiktok",
        "video_id": video_id,
        "source_url": source_url,
        "creator_handle": creator_handle,
        "creator_id": creator_id,
        "published_at": published_at,
        "observed_at": observed_at,
        "age_since_publish_seconds": age_since_publish_seconds,
        "metrics": normalized_metrics,
        "follower_count_at_observation": follower_count_at_observation,
        "collector": collector,
        "notes": notes,
    }
    validate(snapshot, "performance_v0_1")
    return snapshot
