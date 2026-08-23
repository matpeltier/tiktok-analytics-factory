"""Configuration for the two-pass multi-step decompiler.

Credentials come from the environment only. Model IDs and pricing are
explicit configuration, never hardcoded in run code or notebooks.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tiktok_analytics_factory.baseline.config import PricingConfig

PIPELINE_VERSION = "multistep_v1"
RICH_SCHEMA_PATH = Path("schemas/creative_ir_v0_1.json")
PASS_A_PROMPT_PATH = Path("prompts/multistep_pass_a_shot_analysis_v0_2.txt")
PASS_B_PROMPT_PATH = Path("prompts/multistep_pass_b_synthesis_v0_2.txt")
DEFAULT_DERIVED_ROOT = Path("data/derived")
DEFAULT_PERCEPTION_VERSION = "v1"


class MultiStepConfigError(RuntimeError):
    """Raised when multi-step configuration is missing or invalid."""


@dataclass
class MultiStepConfig:
    provider: str
    model_id: str  # Pass A (factual shot analysis)
    synthesis_model_id: str | None = None  # Pass B; None => same model as Pass A
    temperature: float = 0.2
    top_p: float | None = None
    max_output_tokens: int | None = None
    pass_a_prompt_path: Path = PASS_A_PROMPT_PATH
    pass_b_prompt_path: Path = PASS_B_PROMPT_PATH
    schema_path: Path = RICH_SCHEMA_PATH
    derived_root: Path = DEFAULT_DERIVED_ROOT
    perception_version: str = DEFAULT_PERCEPTION_VERSION
    api_key_env: str = "GEMINI_API_KEY"
    pricing: PricingConfig = field(default_factory=PricingConfig)

    @property
    def synthesis_model(self) -> str:
        return self.synthesis_model_id or self.model_id

    @property
    def pass_a_prompt_version(self) -> str:
        return self.pass_a_prompt_path.stem

    @property
    def pass_b_prompt_version(self) -> str:
        return self.pass_b_prompt_path.stem

    def perception_dir(self, video_id: str) -> Path:
        return self.derived_root / video_id / "perception" / self.perception_version

    def decompilation_dir(self, video_id: str, run_id: str) -> Path:
        return (
            self.derived_root
            / video_id
            / "decompilation"
            / "multi_step"
            / run_id
        )

    def require_api_key(self) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise MultiStepConfigError(
                f"Missing API credential: set the {self.api_key_env} environment variable."
            )
        return key

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["pass_a_prompt_path"] = str(self.pass_a_prompt_path)
        d["pass_b_prompt_path"] = str(self.pass_b_prompt_path)
        d["schema_path"] = str(self.schema_path)
        d["derived_root"] = str(self.derived_root)
        d["pipeline_version"] = PIPELINE_VERSION
        return {k: v for k, v in d.items() if "key" not in k}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def load_multistep_config(
    config_path: Path | None = None,
    env: dict[str, str] | None = None,
) -> MultiStepConfig:
    """Load multi-step configuration.

    Precedence: explicit JSON config file -> environment variables ->
    defaults. A concrete model ID must be resolvable; it is never hardcoded.
    """
    env = dict(os.environ if env is None else env)

    file_cfg: dict[str, Any] = {}
    if config_path is not None:
        if not config_path.exists():
            raise MultiStepConfigError(f"Config file not found: {config_path}")
        file_cfg = json.loads(config_path.read_text())

    provider = file_cfg.get("provider") or env.get("MULTISTEP_PROVIDER", "google")
    model_id = (
        file_cfg.get("model_id")
        or env.get("MULTISTEP_MODEL_ID")
        or env.get("GEMINI_MODEL_ID")
    )
    if not model_id:
        raise MultiStepConfigError(
            "No model ID configured. Set MULTISTEP_MODEL_ID (or GEMINI_MODEL_ID), "
            "or pass a JSON config file with a 'model_id' field."
        )
    synthesis_model_id = file_cfg.get("synthesis_model_id") or env.get(
        "MULTISTEP_SYNTHESIS_MODEL_ID"
    )

    pricing_raw = file_cfg.get("pricing") or {}
    pricing = PricingConfig(
        input_per_mtok_usd=pricing_raw.get("input_per_mtok_usd"),
        output_per_mtok_usd=pricing_raw.get("output_per_mtok_usd"),
    )
    if env.get("MULTISTEP_INPUT_PRICE_PER_MTOKEN"):
        pricing.input_per_mtok_usd = float(env["MULTISTEP_INPUT_PRICE_PER_MTOKEN"])
    if env.get("MULTISTEP_OUTPUT_PRICE_PER_MTOKEN"):
        pricing.output_per_mtok_usd = float(env["MULTISTEP_OUTPUT_PRICE_PER_MTOKEN"])

    return MultiStepConfig(
        provider=str(provider),
        model_id=str(model_id),
        synthesis_model_id=(
            str(synthesis_model_id) if synthesis_model_id else None
        ),
        temperature=float(file_cfg.get("temperature", env.get("MULTISTEP_TEMPERATURE", 0.2))),
        top_p=(float(file_cfg["top_p"]) if "top_p" in file_cfg else None),
        max_output_tokens=(
            int(file_cfg["max_output_tokens"]) if "max_output_tokens" in file_cfg else None
        ),
        pass_a_prompt_path=Path(file_cfg.get("pass_a_prompt_path", PASS_A_PROMPT_PATH)),
        pass_b_prompt_path=Path(file_cfg.get("pass_b_prompt_path", PASS_B_PROMPT_PATH)),
        schema_path=Path(file_cfg.get("schema_path", RICH_SCHEMA_PATH)),
        derived_root=Path(file_cfg.get("derived_root", DEFAULT_DERIVED_ROOT)),
        perception_version=str(
            file_cfg.get("perception_version", env.get("MULTISTEP_PERCEPTION_VERSION", DEFAULT_PERCEPTION_VERSION))
        ),
        api_key_env=file_cfg.get("api_key_env", env.get("MULTISTEP_API_KEY_ENV", "GEMINI_API_KEY")),
        pricing=pricing,
    )
