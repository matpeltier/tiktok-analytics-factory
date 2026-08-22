"""Deterministic parsing for the multi-step decompiler.

Reuses the baseline's single deterministic strategy (strip one optional code
fence, then json.loads) and schema validation. No repair passes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tiktok_analytics_factory.baseline.parsing import ParseError, parse_model_output  # re-export
from tiktok_analytics_factory.baseline.parsing import validate_against_schema  # re-export
from tiktok_analytics_factory.contracts import ContractValidationError, validate as contracts_validate

__all__ = [
    "ParseError",
    "parse_model_output",
    "validate_against_schema",
    "ShotAnalysisError",
    "validate_shot_analysis",
    "validate_synthesis",
]


class ShotAnalysisError(RuntimeError):
    pass


_REQUIRED_SHOT_FIELDS = ("shot_id", "subjects", "actions", "visual_description")


def validate_shot_analysis(parsed: dict[str, Any], expected_shot_ids: list[str]) -> None:
    """Structural check of a parsed Pass A response against the shot list.

    Fails loudly when any expected shot is missing or core fields are absent.
    """
    shots = parsed.get("shots")
    if not isinstance(shots, list):
        raise ShotAnalysisError("Pass A response missing 'shots' array")
    by_id: dict[str, dict[str, Any]] = {}
    for entry in shots:
        if not isinstance(entry, dict):
            raise ShotAnalysisError("Pass A 'shots' entries must be objects")
        shot_id = entry.get("shot_id")
        if not isinstance(shot_id, str):
            raise ShotAnalysisError("Pass A shot entry without string 'shot_id'")
        if shot_id in by_id:
            raise ShotAnalysisError(f"Pass A returned duplicate analysis for {shot_id}")
        by_id[shot_id] = entry
    missing = [sid for sid in expected_shot_ids if sid not in by_id]
    if missing:
        raise ShotAnalysisError(f"Pass A did not analyze shots: {missing}")
    extra = [sid for sid in by_id if sid not in set(expected_shot_ids)]
    if extra:
        raise ShotAnalysisError(f"Pass A analyzed unknown shot ids: {extra}")
    for sid in expected_shot_ids:
        entry = by_id[sid]
        for field in _REQUIRED_SHOT_FIELDS:
            if field not in entry:
                raise ShotAnalysisError(f"Pass A shot {sid} missing required field '{field}'")
        description = entry["visual_description"]
        if not isinstance(description, str) or not description.strip():
            raise ShotAnalysisError(f"Pass A shot {sid} has empty visual_description")


def validate_synthesis(parsed: dict[str, Any]) -> None:
    """Structural check of a parsed Pass B response (pre-merge)."""
    required_top = ("observed_summary", "inferred", "generation")
    for key in required_top:
        if key not in parsed:
            raise ShotAnalysisError(f"Pass B response missing '{key}'")
    inferred = parsed.get("inferred")
    if not isinstance(inferred, dict) or "commercial" not in inferred:
        raise ShotAnalysisError("Pass B 'inferred' must be an object containing 'commercial'")
    generation = parsed.get("generation")
    if not isinstance(generation, dict) or not isinstance(generation.get("global_brief"), str):
        raise ShotAnalysisError("Pass B 'generation.global_brief' must be a string")
    gen_shots = generation.get("shots")
    if not isinstance(gen_shots, list):
        raise ShotAnalysisError("Pass B 'generation.shots' must be an array")


def validate_creative_ir(creative_ir: dict[str, Any]) -> None:
    """Validate a merged CreativeIR against the committed v0.1 contract."""
    try:
        contracts_validate(creative_ir, "creative_ir_v0_1")
    except ContractValidationError as exc:
        raise ParseError(f"Merged CreativeIR failed schema validation: {exc}") from exc
