"""Prompt rendering and request construction for the two-pass decompiler.

Pass A: one compact batch request covering all deterministic shots, with the
video and one representative frame per shot attached.
Pass B: synthesis request with metadata, deterministic facts, and validated
Pass A analyses (plus the video for full-video context).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tiktok_analytics_factory.multistep.config import MultiStepConfig


class RequestBuildError(RuntimeError):
    pass


def load_prompt(path: Path) -> str:
    if not path.exists():
        raise RequestBuildError(f"Prompt file not found: {path}")
    return path.read_text()


def render_pass_a_prompt(template: str, shot_list: list[dict[str, Any]]) -> str:
    return template.replace(
        "{shot_list}", json.dumps(shot_list, indent=2)
    )


def build_shot_list(shots_result: dict[str, Any], frames: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Deterministic shot descriptors handed to Pass A.

    Timestamps come verbatim from the #5 perception artifacts; the model is
    never asked to produce them.
    """
    frames_by_shot = {f.get("shot_id"): f for f in (frames or [])}
    shot_list: list[dict[str, Any]] = []
    for shot in shots_result["shots"]:
        entry = {
            "shot_id": shot["shot_id"],
            "start_seconds": shot["start_seconds"],
            "end_seconds": shot["end_seconds"],
            "start_frame": shot["start_frame"],
            "end_frame": shot["end_frame"],
        }
        frame = frames_by_shot.get(shot["shot_id"])
        if frame:
            entry["representative_frame"] = {
                "path": frame["path"],
                "timestamp_seconds": frame["timestamp_seconds"],
            }
        shot_list.append(entry)
    return shot_list


def build_generation_settings(config: MultiStepConfig) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "temperature": config.temperature,
        "response_mime_type": "application/json",
    }
    if config.top_p is not None:
        settings["top_p"] = config.top_p
    if config.max_output_tokens is not None:
        settings["max_output_tokens"] = config.max_output_tokens
    return settings


def _read_frame_bytes(frame_path: str) -> tuple[bytes, str]:
    path = Path(frame_path)
    if not path.exists():
        raise RequestBuildError(f"Representative frame not found: {path}")
    return path.read_bytes(), "image/jpeg"


def build_pass_a_request(
    config: MultiStepConfig,
    video_bytes: bytes,
    shot_list: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Return (rendered_prompt, parts) for the single Pass A batch call.

    ``parts`` are plain dicts (mime_type + data) so tests can run without the
    SDK; the runner converts them to SDK objects.
    """
    prompt = render_pass_a_prompt(load_prompt(config.pass_a_prompt_path), shot_list)
    parts: list[dict[str, Any]] = [
        {"mime_type": "video/mp4", "data": video_bytes, "role": "source_video"}
    ]
    for shot in shot_list:
        frame = shot.get("representative_frame")
        if frame:
            data, mime = _read_frame_bytes(frame["path"])
            parts.append({"mime_type": mime, "data": data, "role": f"frame:{shot['shot_id']}"})
    parts.append({"mime_type": "text/plain", "data": prompt.encode(), "role": "prompt"})
    return prompt, parts


def render_pass_b_prompt(
    template: str,
    source_metadata: dict[str, Any],
    media_facts: dict[str, Any],
    shot_list: list[dict[str, Any]],
    shot_analyses: dict[str, Any],
) -> str:
    return (
        template.replace("{source_metadata}", json.dumps(source_metadata, indent=2))
        .replace("{media_facts}", json.dumps(media_facts, indent=2))
        .replace("{shot_list}", json.dumps(shot_list, indent=2))
        .replace("{shot_analyses}", json.dumps(shot_analyses, indent=2))
    )


def build_pass_b_request(
    config: MultiStepConfig,
    video_bytes: bytes | None,
    source_metadata: dict[str, Any],
    media_facts: dict[str, Any],
    shot_list: list[dict[str, Any]],
    shot_analyses: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    """Return (rendered_prompt, parts) for the Pass B synthesis call."""
    prompt = render_pass_b_prompt(
        load_prompt(config.pass_b_prompt_path),
        source_metadata,
        media_facts,
        shot_list,
        shot_analyses,
    )
    parts: list[dict[str, Any]] = []
    if video_bytes is not None:
        parts.append({"mime_type": "video/mp4", "data": video_bytes, "role": "source_video"})
    parts.append({"mime_type": "text/plain", "data": prompt.encode(), "role": "prompt"})
    return prompt, parts
