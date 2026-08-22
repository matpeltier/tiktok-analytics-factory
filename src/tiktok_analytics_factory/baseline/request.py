"""Prompt rendering and request construction for the single-pass baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tiktok_analytics_factory.baseline.config import BaselineConfig


class RequestBuildError(RuntimeError):
    pass


def load_prompt(config: BaselineConfig) -> str:
    if not config.prompt_path.exists():
        raise RequestBuildError(f"Prompt file not found: {config.prompt_path}")
    return config.prompt_path.read_text()


def load_schema(config: BaselineConfig) -> dict[str, Any]:
    if not config.schema_path.exists():
        raise RequestBuildError(f"Schema file not found: {config.schema_path}")
    return json.loads(config.schema_path.read_text())


def render_prompt(
    template: str,
    source_metadata: dict[str, Any],
    schema: dict[str, Any],
) -> str:
    """Fill the versioned prompt template with metadata and schema."""
    return template.replace(
        "{source_metadata}", json.dumps(source_metadata, indent=2)
    ).replace("{schema_json}", json.dumps(schema, indent=2))


def build_request_contents(
    config: BaselineConfig,
    video_bytes: bytes,
    video_mime_type: str,
    source_metadata: dict[str, Any],
):
    """Return (rendered_prompt_text, parts) for exactly one Gemini call.

    ``parts`` follows the google-genai SDK shape:
    [video_part, prompt_text]. The video is passed once; the prompt carries
    the schema and metadata. No ffprobe/shot-detection/transcript inputs.
    """
    prompt = render_prompt(load_prompt(config), source_metadata, load_schema(config))
    video_part = {"mime_type": video_mime_type, "data": video_bytes}
    return prompt, [video_part, prompt]


def build_generation_settings(config: BaselineConfig) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "temperature": config.temperature,
        "response_mime_type": "application/json",
    }
    if config.top_p is not None:
        settings["top_p"] = config.top_p
    if config.max_output_tokens is not None:
        settings["max_output_tokens"] = config.max_output_tokens
    return settings
