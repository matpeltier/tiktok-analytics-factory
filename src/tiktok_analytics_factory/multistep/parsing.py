"""Deterministic parsing for the multi-step decompiler.

Reuses the baseline's single deterministic strategy (strip one optional code
fence, then json.loads) and schema validation. The only repair allowed is a
narrow fix for malformed ``\\uXXXX`` escapes (truncated escapes and
unpaired surrogates), which Gemini emits occasionally inside exact quotes;
the repaired text is only used when the strict parse fails, and the raw
response is always preserved verbatim by the runner.
"""

from __future__ import annotations

import re
from typing import Any

from tiktok_analytics_factory.baseline.parsing import (  # re-export
    ParseError,
    parse_model_output,
    validate_against_schema,  # re-export
)
from tiktok_analytics_factory.contracts import ContractValidationError
from tiktok_analytics_factory.contracts import validate as contracts_validate

__all__ = [
    "ParseError",
    "ShotAnalysisError",
    "parse_model_output",
    "parse_multistep_model_output",
    "validate_against_schema",
    "validate_shot_analysis",
    "validate_synthesis",
]


_MALFORMED_UNICODE_ESCAPE = re.compile(r"\\u[0-9a-fA-F]{1,4}")


def _repair_malformed_unicode_escapes(text: str) -> str:
    """Drop truncated \\u escapes and unpaired surrogate escapes.

    Only applied as a fallback after a strict json.loads failure. Escaped
    literal backslashes ("\\\\u...") are left untouched because the regex
    requires exactly one leading backslash.
    """

    def _sub(match: re.Match[str]) -> str:
        hexpart = match.group(0)[2:]
        if len(hexpart) < 4:
            return ""  # truncated escape such as \ud
        codepoint = int(hexpart, 16)
        if 0xD800 <= codepoint <= 0xDFFF:
            return ""  # unpaired surrogate
        return match.group(0)

    return _MALFORMED_UNICODE_ESCAPE.sub(_sub, text)


def parse_multistep_model_output(raw: str) -> Any:
    """Strict parse first; on failure, retry after unicode-escape repair."""
    try:
        return parse_model_output(raw)
    except ParseError:
        repaired = _repair_malformed_unicode_escapes(raw)
        if repaired == raw:
            raise
        try:
            return parse_model_output(repaired)
        except ParseError:
            raise


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
