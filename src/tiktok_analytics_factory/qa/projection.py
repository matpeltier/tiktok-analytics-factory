"""Deterministic projection from CreativeIR to the CanonicalIR payload.

This is the single source of truth for the CanonicalIR projection rule so the
pipeline and the QA validator cannot drift. The canonical serialization rule is
``records.canonical_json`` (sorted keys, compact separators); a stored
CanonicalIR matches iff its ``projection`` payload equals this projection under
that serialization.
"""

from __future__ import annotations

from typing import Any


def project_canonical(creative_ir: dict[str, Any] | None) -> dict[str, Any] | None:
    """Project CreativeIR into the compact CanonicalIR payload.

    Deterministic: only observed/deterministic fields are projected; inferred
    creative features are reduced to stable categorical labels. Performance
    metrics are never included.
    """
    if not isinstance(creative_ir, dict):
        return None

    shots_out = []
    for shot in creative_ir.get("shots", []) or []:
        tr = shot.get("time_range") or shot.get("timeline") or {}
        entry: dict[str, Any] = {
            "shot_id": shot.get("shot_id"),
            "start_s": tr.get("start_s"),
            "end_s": tr.get("end_s"),
        }
        for key in ("visual_description", "hook", "narrative_role", "commercial_reasoning"):
            node = shot.get(key)
            if isinstance(node, dict) and node.get("label") is not None:
                entry[key] = {"label": node["label"]}
            elif isinstance(node, str):
                entry[key] = {"label": node}
        texts = [t.get("text") for t in shot.get("text_overlays", []) or [] if t.get("text")]
        dialogue = [d.get("text") for d in shot.get("spoken_dialogue", []) or [] if d.get("text")]
        if texts:
            entry["text_overlays"] = sorted(texts)
        if dialogue:
            entry["spoken_dialogue"] = list(dialogue)
        shots_out.append(entry)

    return {
        "schema_version": creative_ir.get("schema_version"),
        "source_video_id": creative_ir.get("source_video_id"),
        "shots": shots_out,
    }
