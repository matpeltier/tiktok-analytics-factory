"""Artifact persistence for baseline runs.

Layout (git-ignored):

    data/derived/<video_id>/decompilation/single_pass/<run_id>/
        prompt.txt
        request.json
        response.raw.txt
        response.parsed.json
        validation.json
        usage.json
        evaluation.json

Every artifact carries provenance (video id/hash, model ID, prompt version,
settings, timestamps).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tiktok_analytics_factory.baseline.config import BaselineConfig


def new_run_id(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_directory(config: BaselineConfig, video_id: str, run_id: str) -> Path:
    return config.derived_root / video_id / "decompilation" / "single_pass" / run_id


class RunArtifacts:
    """Writes all baseline run artifacts atomically and explicitly."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _write(self, name: str, content: str) -> Path:
        path = self.directory / name
        path.write_text(content)
        return path

    def write_prompt(self, prompt: str) -> Path:
        return self._write("prompt.txt", prompt)

    def write_request(
        self,
        config: BaselineConfig,
        video_id: str,
        video_sha256: str,
        source_metadata: dict[str, Any],
        generation_settings: dict[str, Any],
        started_at: str,
    ) -> Path:
        request = {
            "video_id": video_id,
            "video_sha256": video_sha256,
            "source_metadata": source_metadata,
            "provider": config.provider,
            "model_id": config.model_id,
            "prompt_version": config.prompt_version,
            "generation_settings": generation_settings,
            "single_call": True,
            "started_at": started_at,
        }
        return self._write("request.json", json.dumps(request, indent=2))

    def write_raw_response(self, raw_text: str) -> Path:
        return self._write("response.raw.txt", raw_text)

    def write_parsed_response(self, parsed: dict[str, Any] | None) -> Path:
        return self._write(
            "response.parsed.json",
            json.dumps(parsed if parsed is not None else {"parse_error": True}, indent=2),
        )

    def write_validation(self, validation: dict[str, Any]) -> Path:
        return self._write("validation.json", json.dumps(validation, indent=2))

    def write_usage(
        self,
        config: BaselineConfig,
        usage_metadata: dict[str, Any],
        latency_seconds: float,
        completed_at: str,
    ) -> Path:
        input_tokens = usage_metadata.get("input_tokens")
        output_tokens = usage_metadata.get("output_tokens")
        cost = config.pricing.cost_usd(input_tokens, output_tokens)
        usage = {
            "usage": usage_metadata,
            "latency_seconds": latency_seconds,
            "cost_usd": cost,
            "pricing_input_per_mtok_usd": config.pricing.input_per_mtok_usd,
            "pricing_output_per_mtok_usd": config.pricing.output_per_mtok_usd,
            "completed_at": completed_at,
        }
        return self._write("usage.json", json.dumps(usage, indent=2))

    def write_evaluation(self, evaluation: dict[str, Any]) -> Path:
        return self._write("evaluation.json", json.dumps(evaluation, indent=2))

    @staticmethod
    def utc_now_iso() -> str:
        return datetime.now(UTC).isoformat()
