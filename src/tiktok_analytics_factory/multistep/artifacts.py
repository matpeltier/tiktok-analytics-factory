"""Artifact persistence for multi-step decompilation runs.

Layout (git-ignored), per issue spec:

    data/derived/<video_id>/decompilation/multi_step/<run_id>/
        media_facts.json
        shots.json
        shot_analysis/
            request_*.json
            response_*.raw.txt
            response_*.parsed.json
        synthesis/
            prompt.txt
            response.raw.txt
            response.parsed.json
        creative_ir.json
        canonical_ir.json
        validation.json
        usage.json
        evaluation.json
        comparison_vs_single_pass.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class MultiStepArtifacts:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        (self.directory / "shot_analysis").mkdir(parents=True, exist_ok=True)
        (self.directory / "synthesis").mkdir(parents=True, exist_ok=True)

    def _write_json(self, path: Path, payload: Any) -> Path:
        path.write_text(json.dumps(payload, indent=2) + "\n")
        return path

    # --- deterministic inputs (copies of #5 outputs) -----------------------

    def write_media_facts(self, media_facts: dict[str, Any]) -> Path:
        return self._write_json(self.directory / "media_facts.json", media_facts)

    def write_shots(self, shots: dict[str, Any]) -> Path:
        return self._write_json(self.directory / "shots.json", shots)

    # --- pass A -------------------------------------------------------------

    def write_shot_analysis_request(
        self,
        batch_index: int,
        request_payload: dict[str, Any],
    ) -> Path:
        return self._write_json(
            self.directory / "shot_analysis" / f"request_{batch_index:03d}.json",
            request_payload,
        )

    def write_shot_analysis_raw(self, batch_index: int, raw_text: str) -> Path:
        path = self.directory / "shot_analysis" / f"response_{batch_index:03d}.raw.txt"
        path.write_text(raw_text)
        return path

    def write_shot_analysis_parsed(
        self, batch_index: int, parsed: dict[str, Any] | None
    ) -> Path:
        return self._write_json(
            self.directory / "shot_analysis" / f"response_{batch_index:03d}.parsed.json",
            parsed if parsed is not None else {"parse_error": True},
        )

    # --- pass B -------------------------------------------------------------

    def write_synthesis_prompt(self, prompt: str) -> Path:
        path = self.directory / "synthesis" / "prompt.txt"
        path.write_text(prompt)
        return path

    def write_synthesis_request(self, request_payload: dict[str, Any]) -> Path:
        return self._write_json(
            self.directory / "synthesis" / "request.json", request_payload
        )

    def write_synthesis_raw(self, raw_text: str) -> Path:
        path = self.directory / "synthesis" / "response.raw.txt"
        path.write_text(raw_text)
        return path

    def write_synthesis_parsed(self, parsed: dict[str, Any] | None) -> Path:
        return self._write_json(
            self.directory / "synthesis" / "response.parsed.json",
            parsed if parsed is not None else {"parse_error": True},
        )

    # --- merged outputs -----------------------------------------------------

    def write_creative_ir(self, creative_ir: dict[str, Any]) -> Path:
        return self._write_json(self.directory / "creative_ir.json", creative_ir)

    def write_canonical_ir(self, canonical_ir: dict[str, Any]) -> Path:
        return self._write_json(self.directory / "canonical_ir.json", canonical_ir)

    def write_validation(self, validation: dict[str, Any]) -> Path:
        return self._write_json(self.directory / "validation.json", validation)

    def write_usage(self, usage: dict[str, Any]) -> Path:
        return self._write_json(self.directory / "usage.json", usage)

    def write_evaluation(self, evaluation: dict[str, Any]) -> Path:
        return self._write_json(self.directory / "evaluation.json", evaluation)

    def write_comparison(self, comparison: dict[str, Any]) -> Path:
        return self._write_json(
            self.directory / "comparison_vs_single_pass.json", comparison
        )
