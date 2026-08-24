"""Stage contracts and adapters for the pilot pipeline.

The pilot reuses the validated single-video components (ingestion #2,
performance snapshot #3, deterministic perception #5, validated decompiler
#6). This module defines the narrow interface the batch runner needs and
ships deterministic fakes used by tests/CI. Real adapters are injected by
the caller; nothing here silently falls back.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

PIPELINE_VERSION = "pilot-1.0.0"


class PipelineStageError(Exception):
    """A non-transient stage failure; fails loudly, isolates the video."""

    def __init__(self, stage: str, category: str, message: str):
        super().__init__(f"[{stage}/{category}] {message}")
        self.stage = stage
        self.category = category
        self.message = message


@dataclass
class StageResult:
    """Output of one pipeline stage for one video."""

    ok: bool
    artifacts: dict[str, Any] = field(default_factory=dict)
    usage_cost_usd: float = 0.0
    latency_seconds: float = 0.0
    model_id: str | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    error_category: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ok": self.ok,
            "usage_cost_usd": self.usage_cost_usd,
            "latency_seconds": self.latency_seconds,
        }
        if self.model_id:
            d["model_id"] = self.model_id
        if self.prompt_version:
            d["prompt_version"] = self.prompt_version
        if self.schema_version:
            d["schema_version"] = self.schema_version
        if not self.ok:
            d["error_category"] = self.error_category or "unknown"
            d["error_message"] = self.error_message or ""
        return d


class Stage(Protocol):
    def __call__(self, ctx: VideoContext) -> StageResult: ...


@dataclass
class VideoContext:
    """Everything one video's stages may need. No notebook memory."""

    url: str
    video_id: str | None
    cohort_id: str
    cohort_version: str
    record_dir: Any  # Path
    ingestion: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineStages:
    """Ordered validated stages. Each returns a StageResult."""

    performance_snapshot: Callable[[VideoContext], StageResult]
    perception: Callable[[VideoContext], StageResult]
    decompile: Callable[[VideoContext], StageResult]
    project_canonical: Callable[[VideoContext], StageResult]


def failing_stage(stage: str) -> Callable[[VideoContext], StageResult]:
    """Explicit placeholder that fails loudly when a validated stage is absent."""

    def _run(ctx: VideoContext) -> StageResult:
        return StageResult(
            ok=False,
            error_category="stage_not_available",
            error_message=(
                f"validated {stage} stage is not available in this build; "
                "cannot run pilot without it"
            ),
        )

    return _run
