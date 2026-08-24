"""Runner for the two-pass multi-step decompilation pipeline.

Pipeline:
  MP4 -> deterministic perception (#5, precomputed) -> Pass A factual shot
  analysis (Gemini) -> Pass B global creative synthesis (Gemini) ->
  deterministic provenance merge -> schema validation -> CanonicalIR
  projection.

Any failure fails the run loudly; an invalid CreativeIR is never persisted as
a success.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tiktok_analytics_factory.baseline.artifacts import new_run_id, sha256_bytes
from tiktok_analytics_factory.contracts import (
    ContractValidationError,
    project_creative_to_canonical,
    validate as contracts_validate,
)
from tiktok_analytics_factory.multistep.artifacts import MultiStepArtifacts
from tiktok_analytics_factory.multistep.config import PIPELINE_VERSION, MultiStepConfig
from tiktok_analytics_factory.multistep.evaluation import build_evaluation_scaffold
from tiktok_analytics_factory.multistep.merge import MergeError, merge_creative_ir
from tiktok_analytics_factory.multistep.parsing import (
    ParseError,
    ShotAnalysisError,
    parse_model_output,
    validate_creative_ir,
    validate_shot_analysis,
    validate_synthesis,
)
from tiktok_analytics_factory.multistep.request import (
    RequestBuildError,
    build_generation_settings,
    build_pass_a_request,
    build_pass_b_request,
    build_shot_list,
)


class MultiStepRunError(RuntimeError):
    pass


def _retry_delay_seconds(message: str, attempt: int) -> float:
    """Honor the API's retryDelay when present; exponential backoff otherwise."""
    match = re.search(r"retry in ([\d.]+)s", message)
    if match:
        return float(match.group(1)) + 2.0
    return min(60.0, 5.0 * 2 ** (attempt - 1))


PassCaller = Callable[[list[dict[str, Any]], dict[str, Any]], tuple[str, dict[str, Any]]]


def _call_gemini(config: MultiStepConfig, parts: list[dict[str, Any]], settings: dict[str, Any], model_id: str) -> tuple[str, dict[str, Any]]:
    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError as exc:
        raise MultiStepRunError(
            "The 'google-genai' package is required to run the multi-step "
            "decompiler. Install it (pip install google-genai)."
        ) from exc

    client = genai.Client(api_key=config.require_api_key())
    sdk_parts = []
    for part in parts:
        if part["mime_type"] == "text/plain":
            sdk_parts.append(part["data"].decode())
        else:
            sdk_parts.append(types.Part.from_bytes(data=part["data"], mime_type=part["mime_type"]))
    max_attempts = 6
    for attempt in range(1, max_attempts + 1):
        try:
            _wait_for_model_gap(config.min_model_call_gap_seconds)
            response = client.models.generate_content(
                model=model_id,
                contents=sdk_parts,
                config=types.GenerateContentConfig(**settings),
            )
            break
        except Exception as exc:  # noqa: BLE001 - surfaced below on final attempt
            message = str(exc)
            retriable = "429" in message or "RESOURCE_EXHAUSTED" in message or "503" in message
            if not retriable or attempt == max_attempts:
                raise MultiStepRunError(
                    f"Gemini call failed after {attempt} attempt(s): {message}"
                ) from exc
            delay = _retry_delay_seconds(message, attempt)
            print(f"[multistep] rate-limited; retry {attempt}/{max_attempts - 1} in {delay:.0f}s", file=sys.stderr)
            time.sleep(delay)
    raw_text = response.text or ""
    um = getattr(response, "usage_metadata", None)
    usage_metadata = {}
    if um is not None:
        usage_metadata = {
            "input_tokens": getattr(um, "prompt_token_count", None),
            "output_tokens": getattr(um, "candidates_token_count", None),
            "total_tokens": getattr(um, "total_token_count", None),
        }
    return raw_text, usage_metadata


def _summarize_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Request metadata without embedding megabytes of media bytes."""
    return [
        {"mime_type": p["mime_type"], "role": p.get("role"), "bytes": len(p["data"])}
        for p in parts
    ]


def load_perception_inputs(config: MultiStepConfig, video_id: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    perception_dir = config.perception_dir(video_id)
    facts_path = perception_dir / "media_facts.json"
    shots_path = perception_dir / "shots.json"
    manifest_path = perception_dir / "perception_manifest.json"
    if not facts_path.exists():
        raise MultiStepRunError(f"Missing deterministic perception artifact: {facts_path}")
    media_facts = json.loads(facts_path.read_text())
    if not shots_path.exists():
        raise MultiStepRunError(f"Missing deterministic perception artifact: {shots_path}")
    shots_result = json.loads(shots_path.read_text())
    frames: list[dict[str, Any]] = []
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        frames = manifest.get("frames", [])
    return media_facts, shots_result, frames


def run_multistep(
    config: MultiStepConfig,
    video_path: Path,
    video_id: str,
    source_metadata: dict[str, Any],
    run_id: str | None = None,
    caller: PassCaller | None = None,
    synthesis_caller: PassCaller | None = None,
    include_video_in_synthesis: bool = True,
) -> dict[str, Any]:
    """Execute one two-pass run and persist all artifacts.

    ``caller`` / ``synthesis_caller`` allow tests to inject fake callables with
    signature ``(parts, settings) -> (raw_text, usage_metadata)``.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise MultiStepRunError(f"Reference video not found: {video_path}")

    run_id = run_id or new_run_id()
    directory = config.decompilation_dir(video_id, run_id)
    artifacts = MultiStepArtifacts(directory)

    media_facts, shots_result, frames = load_perception_inputs(config, video_id)
    artifacts.write_media_facts(media_facts)
    artifacts.write_shots(shots_result)

    video_bytes = video_path.read_bytes()
    settings = build_generation_settings(config)

    pass_records: list[dict[str, Any]] = []

    # ---------------- Pass A (batched; batch size 1 by default in v0.3) -----
    shot_list = build_shot_list(shots_result, frames)
    expected_ids = [s["shot_id"] for s in shots_result["shots"]]
    batches = [
        shot_list[i:i + config.pass_a_batch_size]
        for i in range(0, len(shot_list), config.pass_a_batch_size)
    ]
    analyses_by_id: dict[str, dict[str, Any]] = {}
    uncertainties: list[str] = []
    pass_a_artifact_refs: list[str] = []
    for batch_index, batch in enumerate(batches):
        prompt_a, parts_a = build_pass_a_request(config, video_bytes, batch)
        batch_ids = [s["shot_id"] for s in batch]
        started_at = datetime.now(timezone.utc).isoformat()
        artifacts.write_shot_analysis_request(batch_index, {
            "video_id": video_id,
            "video_sha256": sha256_bytes(video_bytes),
            "provider": config.provider,
            "model_id": config.model_id,
            "prompt_version": config.pass_a_prompt_version,
            "generation_settings": settings,
            "shot_ids": batch_ids,
            "parts": _summarize_parts(parts_a),
            "started_at": started_at,
        })

        t0 = time.monotonic()
        if caller is None:
            raw_a, usage_a = _call_gemini(config, parts_a, settings, config.model_id)
        else:
            raw_a, usage_a = caller(parts_a, settings)
        latency_a = round(time.monotonic() - t0, 3)
        artifacts.write_shot_analysis_raw(batch_index, raw_a)

        try:
            parsed_a = parse_model_output(raw_a)
        except ParseError as exc:
            artifacts.write_shot_analysis_parsed(batch_index, None)
            raise MultiStepRunError(f"Pass A parse failure (batch {batch_index}): {exc}") from exc
        artifacts.write_shot_analysis_parsed(batch_index, parsed_a)
        try:
            validate_shot_analysis(parsed_a, batch_ids)
        except ShotAnalysisError as exc:
            raise MultiStepRunError(
                f"Pass A response invalid (batch {batch_index}): {exc}"
            ) from exc

        for entry in parsed_a["shots"]:
            analyses_by_id[entry["shot_id"]] = entry
        uncertainties.extend(parsed_a.get("uncertainties") or [])
        pass_a_artifact_refs.append(f"shot_analysis/response_{batch_index:03d}.raw.txt")

        pass_records.append({
            "pass": f"A_factual_shot_analysis_batch_{batch_index:03d}",
            "shot_ids": batch_ids,
            "model_id": config.model_id,
            "prompt_version": config.pass_a_prompt_version,
            "latency_seconds": latency_a,
            "usage": usage_a,
            "cost_usd": config.pricing.cost_usd(
                usage_a.get("input_tokens"), usage_a.get("output_tokens")
            ),
        })

    combined_analyses = {
        "shots": [analyses_by_id[sid] for sid in expected_ids],
        "uncertainties": uncertainties,
    }

    # ---------------- Pass B ----------------
    synthesis_model = config.synthesis_model
    prompt_b, parts_b = build_pass_b_request(
        config,
        video_bytes if include_video_in_synthesis else None,
        source_metadata,
        media_facts,
        shot_list,
        combined_analyses,
    )
    artifacts.write_synthesis_prompt(prompt_b)
    artifacts.write_synthesis_request({
        "video_id": video_id,
        "video_sha256": sha256_bytes(video_bytes) if include_video_in_synthesis else None,
        "provider": config.provider,
        "model_id": synthesis_model,
        "prompt_version": config.pass_b_prompt_version,
        "generation_settings": settings,
        "includes_video": include_video_in_synthesis,
        "parts": _summarize_parts(parts_b),
        "started_at": datetime.now(timezone.utc).isoformat(),
    })

    t0 = time.monotonic()
    effective_b = synthesis_caller or caller
    if effective_b is None:
        raw_b, usage_b = _call_gemini(config, parts_b, settings, synthesis_model)
    else:
        raw_b, usage_b = effective_b(parts_b, settings)
    latency_b = round(time.monotonic() - t0, 3)
    artifacts.write_synthesis_raw(raw_b)

    try:
        parsed_b = parse_model_output(raw_b)
        artifacts.write_synthesis_parsed(parsed_b)
        validate_synthesis(parsed_b)
    except ParseError as exc:
        raise MultiStepRunError(f"Pass B parse failure: {exc}") from exc

    pass_records.append({
        "pass": "B_global_creative_synthesis",
        "model_id": synthesis_model,
        "prompt_version": config.pass_b_prompt_version,
        "latency_seconds": latency_b,
        "usage": usage_b,
        "cost_usd": config.pricing.cost_usd(
            usage_b.get("input_tokens"), usage_b.get("output_tokens")
        ),
    })

    # ---------------- Deterministic merge + validation ----------------
    created_at = datetime.now(timezone.utc).isoformat()
    decompilation_block = {
        "schema_version": "0.1",
        "pipeline_version": f"{PIPELINE_VERSION}",
        "model_id": f"{config.model_id} (pass A) + {synthesis_model} (pass B)",
        "provider": config.provider,
        "prompt_version": (
            f"{config.pass_a_prompt_version} (pass A) + "
            f"{config.pass_b_prompt_version} (pass B)"
        ),
        "created_at": created_at,
        "annotation_mode": "automated",
    }

    try:
        creative_ir = merge_creative_ir(
            source_metadata=source_metadata,
            media_facts=media_facts,
            shots_result=shots_result,
            shot_analyses_parsed=combined_analyses,
            synthesis_parsed=parsed_b,
            decompilation=decompilation_block,
            pass_a_artifact_refs=pass_a_artifact_refs,
            synthesis_artifact_refs=["synthesis/response.raw.txt"],
        )
    except MergeError as exc:
        validation = {
            "valid": False,
            "stage": "merge",
            "errors": [{"path": "/", "message": str(exc)}],
        }
        artifacts.write_validation(validation)
        raise MultiStepRunError(f"Merge failure: {exc}") from exc

    try:
        validate_creative_ir(creative_ir)
    except ParseError as exc:
        artifacts.write_validation({"valid": False, "stage": "creative_ir_schema", "errors": [{"path": "/", "message": str(exc)}]})
        artifacts.write_creative_ir(creative_ir)
        raise MultiStepRunError(str(exc)) from exc

    try:
        canonical_ir = project_creative_to_canonical(creative_ir)
    except ContractValidationError as exc:
        artifacts.write_validation({
            "valid": False,
            "stage": "canonical_projection",
            "errors": [{"path": "/", "message": str(exc)}],
        })
        artifacts.write_creative_ir(creative_ir)
        raise MultiStepRunError(f"Canonical projection failed: {exc}") from exc

    artifacts.write_creative_ir(creative_ir)
    artifacts.write_canonical_ir(canonical_ir)
    artifacts.write_validation({
        "valid": True,
        "stage": "complete",
        "creative_ir_schema": "pass",
        "canonical_projection": "pass",
    })

    total_usage = {
        "input_tokens": sum((p["usage"].get("input_tokens") or 0) for p in pass_records),
        "output_tokens": sum((p["usage"].get("output_tokens") or 0) for p in pass_records),
        "total_tokens": sum((p["usage"].get("total_tokens") or 0) for p in pass_records),
    }
    costs = [p["cost_usd"] for p in pass_records]
    usage_report = {
        "passes": pass_records,
        "model_call_count": len(pass_records),
        "total_usage": total_usage,
        "total_cost_usd": (
            round(sum(c for c in costs if c is not None), 6)
            if all(c is not None for c in costs) else None
        ),
        "total_latency_seconds": round(sum(p["latency_seconds"] for p in pass_records), 3),
        "pricing_input_per_mtok_usd": config.pricing.input_per_mtok_usd,
        "pricing_output_per_mtok_usd": config.pricing.output_per_mtok_usd,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    artifacts.write_usage(usage_report)
    artifacts.write_evaluation(
        build_evaluation_scaffold(creative_ir, media_facts, shots_result, usage_report)
    )

    return {
        "run_id": run_id,
        "directory": str(directory),
        "pipeline_version": PIPELINE_VERSION,
        "model_calls": len(pass_records),
        "usage": usage_report,
        "creative_ir": creative_ir,
        "canonical_ir": canonical_ir,
    }
