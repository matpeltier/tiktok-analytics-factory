"""Configuration for the single-pass baseline.

All provider/model settings come from project config or environment variables,
never from notebook prose. Credentials are read from the environment only.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path("schemas/creative_ir_v0_1.schema.json")
PROMPT_PATH = Path("prompts/single_pass_creative_ir_v0_1.txt")
DEFAULT_DERIVED_ROOT = Path("data/derived")


class BaselineConfigError(RuntimeError):
    """Raised when baseline configuration is missing or invalid."""


@dataclass
class PricingConfig:
    """USD per million tokens; loaded from explicit pricing configuration."""

    input_per_mtok_usd: float | None = None
    output_per_mtok_usd: float | None = None

    def cost_usd(self, input_tokens: int | None, output_tokens: int | None) -> float | None:
        if self.input_per_mtok_usd is None or self.output_per_mtok_usd is None:
            return None
        if input_tokens is None or output_tokens is None:
            return None
        return round(
            (input_tokens / 1_000_000) * self.input_per_mtok_usd
            + (output_tokens / 1_000_000) * self.output_per_mtok_usd,
            6,
        )


@dataclass
class BaselineConfig:
    provider: str
    model_id: str
    temperature: float = 0.2
    top_p: float | None = None
    max_output_tokens: int | None = None
    prompt_path: Path = PROMPT_PATH
    schema_path: Path = SCHEMA_PATH
    derived_root: Path = DEFAULT_DERIVED_ROOT
    api_key_env: str = "GEMINI_API_KEY"
    pricing: PricingConfig = field(default_factory=PricingConfig)

    @property
    def prompt_version(self) -> str:
        return self.prompt_path.stem

    def require_api_key(self) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise BaselineConfigError(
                f"Missing API credential: set the {self.api_key_env} environment variable."
            )
        return key

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["prompt_path"] = str(self.prompt_path)
        d["schema_path"] = str(self.schema_path)
        d["derived_root"] = str(self.derived_root)
        d["prompt_version"] = self.prompt_version
        # Never serialize credentials.
        return {k: v for k, v in d.items() if "key" not in k}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def load_baseline_config(
    config_path: Path | None = None,
    env: dict[str, str] | None = None,
) -> BaselineConfig:
    """Load baseline model configuration.

    Precedence: explicit JSON config file -> environment variables ->
    defaults. The exact provider/model ID must be resolvable from config/env;
    it is never hardcoded in notebooks or run code.
    """
    env = dict(os.environ if env is None else env)

    file_cfg: dict[str, Any] = {}
    if config_path is not None:
        if not config_path.exists():
            raise BaselineConfigError(f"Config file not found: {config_path}")
        file_cfg = json.loads(config_path.read_text())

    provider = file_cfg.get("provider") or env.get("BASELINE_PROVIDER", "google")
    model_id = (
        file_cfg.get("model_id")
        or env.get("BASELINE_MODEL_ID")
        or env.get("GEMINI_MODEL_ID")
    )
    if not model_id:
        raise BaselineConfigError(
            "No model ID configured. Set BASELINE_MODEL_ID (or GEMINI_MODEL_ID), "
            "or pass a JSON config file with a 'model_id' field."
        )

    pricing_raw = file_cfg.get("pricing") or {}
    pricing = PricingConfig(
        input_per_mtok_usd=pricing_raw.get("input_per_mtok_usd"),
        output_per_mtok_usd=pricing_raw.get("output_per_mtok_usd"),
    )
    if env.get("BASELINE_INPUT_PRICE_PER_MTOKEN"):
        pricing.input_per_mtok_usd = float(env["BASELINE_INPUT_PRICE_PER_MTOKEN"])
    if env.get("BASELINE_OUTPUT_PRICE_PER_MTOKEN"):
        pricing.output_per_mtok_usd = float(env["BASELINE_OUTPUT_PRICE_PER_MTOKEN"])

    return BaselineConfig(
        provider=str(provider),
        model_id=str(model_id),
        temperature=float(file_cfg.get("temperature", env.get("BASELINE_TEMPERATURE", 0.2))),
        top_p=(float(file_cfg["top_p"]) if "top_p" in file_cfg else None),
        max_output_tokens=(
            int(file_cfg["max_output_tokens"]) if "max_output_tokens" in file_cfg else None
        ),
        prompt_path=Path(file_cfg.get("prompt_path", PROMPT_PATH)),
        schema_path=Path(file_cfg.get("schema_path", SCHEMA_PATH)),
        derived_root=Path(file_cfg.get("derived_root", DEFAULT_DERIVED_ROOT)),
        api_key_env=file_cfg.get("api_key_env", env.get("BASELINE_API_KEY_ENV", "GEMINI_API_KEY")),
        pricing=pricing,
    )
