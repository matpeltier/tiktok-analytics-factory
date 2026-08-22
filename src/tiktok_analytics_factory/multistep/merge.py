"""Deterministic provenance merge of Pass A + Pass B outputs into CreativeIR v0.1.

Rules enforced here:
- Shot boundaries ALWAYS come from the #5 perception artifacts. The model can
  never introduce or alter them; an explicit conflicting timestamp in a Pass A
  payload raises :class:`MergeError`.
- Deterministic facts carry ``kind: "deterministic"`` evidence references;
  model-derived content carries ``kind: "model_observation"``.
"""

from __future__ import annotations

from typing import Any

PIPELINE_VERSION = "multistep_v1"

_FRAMING = ("extreme_close_up", "close_up", "medium", "wide", "extreme_wide")
_CAMERA_MOVEMENT = ("static", "handheld", "pan", "tilt", "zoom_in", "zoom_out", "tracking")
_TRANSITIONS = ("cut", "jump_cut", "whip_pan", "match_cut", "fade", "wipe", "none_single_shot")
_CERTAINTIES = ("observed", "uncertain", "absent", "unknown")
_HOOK_TYPES = (
    "question", "bold_claim", "curiosity_gap", "visual_shock", "direct_address",
    "problem_statement", "before_after_tease", "social_proof_open", "other",
)
_NARRATIVE = (
    "problem_solution", "before_after", "tutorial_steps", "storytime",
    "listicle", "single_beat_no_narrative", "other",
)
_CONFIDENCES = ("high", "medium", "low")
_CTA_TYPES = (
    "link_in_bio", "follow", "comment", "share", "save", "shop_now",
    "affiliate_link", "other",
)


class MergeError(RuntimeError):
    pass


def _enum_or(value: Any, allowed: tuple[str, ...], fallback: str) -> str:
    return value if isinstance(value, str) and value in allowed else fallback


def _confidence(value: Any) -> str:
    return value if isinstance(value, str) and value in _CONFIDENCES else "low"


def _det_ref(reference: str) -> dict[str, str]:
    return {"kind": "deterministic", "reference": reference}


def _model_ref(reference: str) -> dict[str, str]:
    return {"kind": "model_observation", "reference": reference}


def check_no_boundary_overwrite(
    shot_analysis_entry: dict[str, Any],
    deterministic_shot: dict[str, Any],
) -> None:
    """Reject explicit model attempts to restate/alter deterministic bounds."""
    for key in ("start_seconds", "end_seconds"):
        if key in shot_analysis_entry:
            model_value = shot_analysis_entry[key]
            det_value = deterministic_shot[key]
            if not isinstance(model_value, (int, float)) or abs(float(model_value) - float(det_value)) > 1e-6:
                raise MergeError(
                    f"{deterministic_shot['shot_id']}: model attempted to set "
                    f"{key}={model_value!r}; deterministic value "
                    f"{det_value!r} cannot be overwritten"
                )


def build_source_block(source_metadata: dict[str, Any], media_facts: dict[str, Any]) -> dict[str, Any]:
    raw = source_metadata.get("raw") if isinstance(source_metadata.get("raw"), dict) else source_metadata
    published_at = raw.get("timestamp")
    return {
        "platform": "tiktok",
        "video_id": str(raw.get("id") or source_metadata.get("video_id")),
        "source_url": raw.get("webpage_url") or f"https://www.tiktok.com/@x/video/{raw.get('id')}",
        "creator_handle": raw.get("uploader"),
        "caption": raw.get("description"),
        "hashtags": [
            tag.lstrip("#") for tag in (raw.get("description") or "").split()
            if tag.startswith("#")
        ],
        "duration_seconds": media_facts.get("duration_seconds"),
        "published_at": (
            __import__("datetime").datetime.fromtimestamp(published_at, tz=__import__("datetime").timezone.utc).isoformat()
            if isinstance(published_at, (int, float)) else None
        ),
        "artifact_sha256": media_facts.get("sha256"),
        "manifest_reference": source_metadata.get("manifest_reference"),
    }


def _merge_audio(entry_audio: Any) -> dict[str, Any]:
    audio: dict[str, Any] = {}
    if not isinstance(entry_audio, dict):
        return audio
    for base in ("music", "sfx", "ambience"):
        certainty_key = f"{base}_certainty"
        if base in entry_audio:
            audio[base] = entry_audio[base] if isinstance(entry_audio[base], (str, type(None))) else str(entry_audio[base])
        if certainty_key in entry_audio:
            audio[certainty_key] = _enum_or(entry_audio[certainty_key], _CERTAINTIES, "unknown")
    return audio


def merge_pass_a_shot(
    analysis_entry: dict[str, Any],
    deterministic_shot: dict[str, Any],
    artifact_refs: list[str],
) -> dict[str, Any]:
    """Merge one Pass A entry into a schema-shaped observed.shots entry."""
    check_no_boundary_overwrite(analysis_entry, deterministic_shot)

    on_screen_text = []
    for item in analysis_entry.get("on_screen_text") or []:
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
            on_screen_text.append({"text": item["text"], "exact": bool(item.get("exact"))})

    spoken = []
    for item in analysis_entry.get("spoken_dialogue") or []:
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
            spoken.append({
                "speaker": item.get("speaker") if isinstance(item.get("speaker"), (str, type(None))) else None,
                "text": item["text"],
                # exact only for verbatim transcription; uncertainty downgrades it
                "exact": bool(item.get("exact")) and _confidence(item.get("confidence")) == "high",
            })

    return {
        "shot_id": deterministic_shot["shot_id"],
        "start_seconds": deterministic_shot["start_seconds"],
        "end_seconds": deterministic_shot["end_seconds"],
        "subjects": [s for s in (analysis_entry.get("subjects") or []) if isinstance(s, str)],
        "actions": [a for a in (analysis_entry.get("actions") or []) if isinstance(a, str)],
        "visual_description": analysis_entry["visual_description"],
        "framing": _enum_or(analysis_entry.get("framing"), _FRAMING, "unknown"),
        "camera_movement": _enum_or(analysis_entry.get("camera_movement"), _CAMERA_MOVEMENT, "unknown"),
        "on_screen_text": on_screen_text,
        "spoken_dialogue": spoken,
        "audio": _merge_audio(analysis_entry.get("audio")),
        "transition_in": _enum_or(analysis_entry.get("transition_in"), _TRANSITIONS, "unknown"),
        "evidence": [
            _det_ref(
                f"perception shots.json#{deterministic_shot['shot_id']} "
                f"[{deterministic_shot['start_seconds']}-{deterministic_shot['end_seconds']}s]"
            )
        ]
        + [_model_ref(ref) for ref in artifact_refs],
    }


def _labeled(block: Any, default_label: str | None = None) -> dict[str, Any]:
    if not isinstance(block, dict):
        return {"value": default_label, "confidence": "low", "rationale": None}
    return {
        "value": block.get("value") if isinstance(block.get("value"), (str, type(None))) else str(block.get("value")),
        "confidence": _confidence(block.get("confidence")),
        "rationale": block.get("rationale") if isinstance(block.get("rationale"), (str, type(None))) else None,
    }


def _labeled_free_single(block: Any) -> dict[str, Any] | None:
    """Schema shape for hook_mechanism: a single labeled_free object or None."""
    if isinstance(block, dict) and isinstance(block.get("label"), str):
        return {"label": block["label"], "confidence": _confidence(block.get("confidence")), "rationale": block.get("rationale")}
    return None


def _labeled_free_list(items: Any) -> list[dict[str, Any]]:
    out = []
    for item in items or []:
        if isinstance(item, dict) and isinstance(item.get("label"), str):
            out.append({"label": item["label"], "confidence": _confidence(item.get("confidence")), "rationale": item.get("rationale")})
        elif isinstance(item, str):
            out.append({"label": item, "confidence": "low", "rationale": None})
    return out


def _commercial(block: Any) -> dict[str, Any]:
    status = block.get("status") if isinstance(block, dict) else None
    status = status if status in ("commercial", "non_commercial", "uncertain") else "uncertain"
    details = block.get("details") if isinstance(block, dict) else None
    if status == "non_commercial":
        return {"status": status, "details": None}
    if status == "commercial":
        if not isinstance(details, dict):
            raise MergeError("Pass B commercial.status='commercial' requires 'details'")
    merged_details: dict[str, Any] = {"product_presence": None}
    if isinstance(details, dict):
        for key in (
            "product_presence", "first_product_appearance_seconds", "problem_desire",
            "promise_claim", "offer",
        ):
            if key in details:
                merged_details[key] = details[key]
        proof = details.get("proof_type")
        if proof in ("demonstration", "before_after", "testimonial", "credentials", "data_stats", "social_proof"):
            merged_details["proof_type"] = proof
        else:
            merged_details["proof_type"] = "unknown" if proof == "unknown" else None
        merged_details["trust_signals"] = [t for t in (details.get("trust_signals") or []) if isinstance(t, str)]
        merged_details["objections"] = [o for o in (details.get("objections") or []) if isinstance(o, str)]
        cta = details.get("cta")
        if isinstance(cta, dict):
            cta_type = cta.get("type") if cta.get("type") in _CTA_TYPES else "other"
            merged_details["cta"] = {
                "text": cta.get("text") if isinstance(cta.get("text"), (str, type(None))) else None,
                "text_exact": cta.get("text_exact") if isinstance(cta.get("text_exact"), (bool, type(None))) else None,
                "type": cta_type,
            }
    return {"status": status, "details": merged_details}


def merge_synthesis(
    synthesis: dict[str, Any],
    expected_shot_ids: list[str],
    artifact_refs: list[str],
) -> dict[str, Any]:
    """Map the Pass B synthesis payload onto observed/inferred/generation blocks."""
    known_ids = set(expected_shot_ids)

    hook_block = synthesis.get("hook") or {}
    evidence_refs = (
        [_model_ref(str(ref)) for ref in hook_block["evidence"]]
        if hook_block.get("evidence")
        else [_model_ref("synthesis/response.raw.txt#hook")]
    )
    hook = {
        "description": hook_block.get("description") if isinstance(hook_block.get("description"), (str, type(None))) else None,
        "evidence": evidence_refs,
    }
    for key in ("start_seconds", "end_seconds"):
        if isinstance(hook_block.get(key), (int, float)):
            hook[key] = float(hook_block[key])

    inferred_in = synthesis.get("inferred") or {}
    inferred = {
        "concept": _labeled(inferred_in.get("concept")),
        "target_audience_hypothesis": _labeled(inferred_in.get("target_audience_hypothesis")),
        "hook_type": _labeled(inferred_in.get("hook_type")),
        "hook_mechanism": _labeled_free_single(inferred_in.get("hook_mechanism")),
        "narrative_structure": _labeled(inferred_in.get("narrative_structure")),
        "attention_mechanisms": _labeled_free_list(inferred_in.get("attention_mechanisms")),
        "persuasion_mechanisms": _labeled_free_list(inferred_in.get("persuasion_mechanisms")),
        "commercial": _commercial(inferred_in.get("commercial")),
    }
    # closed enums fall back to "unknown"
    if inferred["hook_type"]["value"] not in _HOOK_TYPES:
        inferred["hook_type"]["value"] = "unknown"
    if inferred["narrative_structure"]["value"] not in _NARRATIVE:
        inferred["narrative_structure"]["value"] = "unknown"

    gen_in = synthesis.get("generation") or {}
    gen_shots = []
    for entry in gen_in.get("shots") or []:
        if isinstance(entry, dict) and entry.get("shot_id") in known_ids:
            gen_shots.append({
                "shot_id": entry["shot_id"],
                "reconstruction_intent": str(entry.get("reconstruction_intent") or ""),
            })
        elif isinstance(entry, dict) and entry.get("shot_id") not in known_ids:
            raise MergeError(
                f"Pass B generation references unknown shot_id {entry.get('shot_id')!r}"
            )

    generation = {
        "global_brief": str(gen_in.get("global_brief") or synthesis.get("observed_summary") or ""),
        "timeline_pacing": gen_in.get("timeline_pacing") if isinstance(gen_in.get("timeline_pacing"), (str, type(None))) else None,
        "text_treatment": gen_in.get("text_treatment") if isinstance(gen_in.get("text_treatment"), (str, type(None))) else None,
        "transitions": gen_in.get("transitions") if isinstance(gen_in.get("transitions"), (str, type(None))) else None,
        "continuity_constraints": [c for c in (gen_in.get("continuity_constraints") or []) if isinstance(c, str)],
        "payoff_timing": gen_in.get("payoff_timing") if isinstance(gen_in.get("payoff_timing"), (str, type(None))) else None,
        "shots": gen_shots,
    }

    observed_partial = {
        "summary": str(synthesis.get("observed_summary") or ""),
        "hook": hook,
    }
    for key in ("narrative_evidence", "marketing_evidence"):
        if synthesis.get(key) is not None:
            observed_partial[key] = synthesis[key]
    fps = synthesis.get("first_product_appearance_seconds")
    if isinstance(fps, (int, float)):
        observed_partial["first_product_appearance_seconds"] = float(fps)

    return observed_partial, inferred, generation


def merge_creative_ir(
    *,
    source_metadata: dict[str, Any],
    media_facts: dict[str, Any],
    shots_result: dict[str, Any],
    shot_analyses_parsed: dict[str, Any],
    synthesis_parsed: dict[str, Any],
    decompilation: dict[str, Any],
    pass_a_artifact_refs: list[str] | None = None,
    synthesis_artifact_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Build the full rich CreativeIR v0.1 dict deterministically.

    ``decompilation`` must contain the run provenance (schema_version,
    pipeline_version, model/provider/prompt versions, created_at,
    annotation_mode).
    """
    deterministic_shots = shots_result["shots"]
    expected_ids = [s["shot_id"] for s in deterministic_shots]
    by_id = {s["shot_id"]: s for s in (shot_analyses_parsed.get("shots") or [])}

    pass_a_refs = pass_a_artifact_refs or ["shot_analysis/response_000.raw.txt"]
    syn_refs = synthesis_artifact_refs or ["synthesis/response.raw.txt"]

    shots_out = []
    for det in deterministic_shots:
        entry = by_id.get(det["shot_id"])
        if entry is None:
            raise MergeError(f"No Pass A analysis for {det['shot_id']}")
        shots_out.append(merge_pass_a_shot(entry, det, pass_a_refs))

    observed_partial, inferred, generation = merge_synthesis(synthesis_parsed, expected_ids, syn_refs)
    if not observed_partial["summary"]:
        raise MergeError("Pass B produced no observed_summary")

    creative_ir: dict[str, Any] = {
        "schema": {"name": "creative_ir", "version": "0.1"},
        "source": build_source_block(source_metadata, media_facts),
        "decompilation": dict(decompilation),
        "observed": {"summary": observed_partial.pop("summary"), "shots": shots_out, **observed_partial},
        "inferred": inferred,
        "generation": generation,
    }
    return creative_ir
