"""Runner: exactly one primary Gemini decompilation call per run."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from tiktok_analytics_factory.baseline.artifacts import (
    RunArtifacts,
    new_run_id,
    run_directory,
    sha256_bytes,
)
from tiktok_analytics_factory.baseline.config import BaselineConfig
from tiktok_analytics_factory.baseline.parsing import (
    ParseError,
    parse_model_output,
    validate_against_schema,
)
from tiktok_analytics_factory.baseline.request import (
    build_generation_settings,
    build_request_contents,
)


class BaselineRunError(RuntimeError):
    pass


def _call_gemini(config: BaselineConfig, parts: list[Any], settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Make the single primary call. Fails loudly if the SDK is missing."""
    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError as exc:
        raise BaselineRunError(
            "The 'google-genai' package is required to run the baseline. "
            "Install it (pip install google-genai)."
        ) from exc

    client = genai.Client(api_key=config.require_api_key())
    video_part = types.Part.from_bytes(data=parts[0]["data"], mime_type=parts[0]["mime_type"])
    response = client.models.generate_content(
        model=config.model_id,
        contents=[video_part, parts[1]],
        config=types.GenerateContentConfig(**settings),
    )
    raw_text = response.text or ""
    usage_metadata = {}
    um = getattr(response, "usage_metadata", None)
    if um is not None:
        usage_metadata = {
            "input_tokens": getattr(um, "prompt_token_count", None),
            "output_tokens": getattr(um, "candidates_token_count", None),
            "total_tokens": getattr(um, "total_token_count", None),
        }
    return raw_text, usage_metadata


def run_baseline(
    config: BaselineConfig,
    video_path: Path,
    video_id: str,
    source_metadata: dict[str, Any],
    run_id: str | None = None,
    caller: Any = None,
) -> dict[str, Any]:
    """Execute one baseline run and persist all artifacts.

    ``caller`` allows tests to inject a fake single-call function with the
    signature ``caller(parts, settings) -> (raw_text, usage_metadata)``.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise BaselineRunError(f"Reference video not found: {video_path}")

    run_id = run_id or new_run_id()
    directory = run_directory(config, video_id, run_id)
    artifacts = RunArtifacts(directory)

    video_bytes = video_path.read_bytes()
    prompt, parts = build_request_contents(
        config, video_bytes, "video/mp4", source_metadata
    )
    settings = build_generation_settings(config)
    started_at = RunArtifacts.utc_now_iso()

    artifacts.write_prompt(prompt)
    artifacts.write_request(
        config,
        video_id,
        sha256_bytes(video_bytes),
        source_metadata,
        settings,
        started_at,
    )

    t0 = time.monotonic()
    if caller is None:
        raw_text, usage_metadata = _call_gemini(config, parts, settings)
    else:
        raw_text, usage_metadata = caller(parts, settings)
    latency_seconds = round(time.monotonic() - t0, 3)

    artifacts.write_raw_response(raw_text)

    parsed: dict[str, Any] | None = None
    validation: dict[str, Any] = {"valid": False, "errors": []}
    try:
        parsed = parse_model_output(raw_text)
        artifacts.write_parsed_response(parsed)
        validation = validate_against_schema(parsed, config.schema_path)
    except ParseError as exc:
        # Malformed output is an explicit baseline failure, recorded not repaired.
        artifacts.write_parsed_response(None)
        validation = {
            "valid": False,
            "errors": [{"path": "/", "message": f"parse failure: {exc}"}],
        }
    artifacts.write_validation(validation)

    completed_at = RunArtifacts.utc_now_iso()
    artifacts.write_usage(config, usage_metadata, latency_seconds, completed_at)

    return {
        "run_id": run_id,
        "directory": str(directory),
        "model_id": config.model_id,
        "prompt_version": config.prompt_version,
        "latency_seconds": latency_seconds,
        "usage": usage_metadata,
        "cost_usd": config.pricing.cost_usd(
            usage_metadata.get("input_tokens"), usage_metadata.get("output_tokens")
        ),
        "validation": validation,
        "parsed": parsed,
    }
