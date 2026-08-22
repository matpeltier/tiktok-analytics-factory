"""Deterministic parsing and schema validation of the model response.

No second LLM call, no silent repair. Malformed JSON or schema failure is
recorded as an explicit baseline failure.
"""

from __future__ import annotations

import json
import re
from typing import Any


class ParseError(RuntimeError):
    pass


_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n(.*)\n```\s*$", re.DOTALL)


def parse_model_output(raw_text: str) -> dict[str, Any]:
    """Parse the raw model output into a JSON object.

    Exactly one deterministic strategy: strip a single optional code fence,
    then ``json.loads``. Anything else raises ParseError.
    """
    text = raw_text.strip()
    fence = _FENCE_RE.match(text)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"Model output is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ParseError(
            f"Model output must be a JSON object, got {type(parsed).__name__}"
        )
    return parsed


def validate_against_schema(
    instance: Any, schema_path: str | Any
) -> dict[str, Any]:
    """Validate against the committed CreativeIR v0.1 JSON Schema.

    Returns ``{"valid": bool, "errors": [...]}``. Uses ``jsonschema`` when
    available; otherwise fails loudly rather than skipping validation.
    """
    from pathlib import Path

    path = Path(schema_path)
    if not path.exists():
        raise FileNotFoundError(f"Schema file not found: {path}")
    schema = json.loads(path.read_text())
    try:
        import jsonschema  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "The 'jsonschema' package is required for CreativeIR validation. "
            "Install it (pip install jsonschema); validation is never skipped."
        ) from exc

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    return {
        "valid": not errors,
        "errors": [
            {
                "path": "/" + "/".join(str(p) for p in err.absolute_path),
                "message": err.message,
            }
            for err in errors
        ],
    }
