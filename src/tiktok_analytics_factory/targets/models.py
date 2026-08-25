"""Versioned record model for derived performance targets.

Every target record references its source Performance snapshot, cohort, method,
intermediate quantities, and code revision. Unknown values stay ``None``; a
target that cannot be validly computed is marked invalid with an explicit
reason rather than fabricated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

TARGET_SCHEMA_VERSION = "performance_target_v0_1"

#: Post-age policy implemented by this schema version. See
#: docs/performance_target.md for the full rationale.
AGE_POLICY = "explicit_age_adjustment_with_window_fallback"


class InvalidTargetError(ValueError):
    """Raised when a target is requested but its inputs are unusable."""


@dataclass
class PerformanceTargetRecord:
    video_id: str
    source_snapshot_id: str
    source_snapshot_version: str
    cohort_id: str
    cohort_version: str
    target_version: str  # e.g. "performance_target_v0_1+method:<hash12>"
    target_schema_version: str = TARGET_SCHEMA_VERSION
    age_policy: str = AGE_POLICY

    # --- intermediate quantities (all nullable, never imputed) ---
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    published_at: str | None = None
    observed_at: str | None = None
    post_age_days: float | None = None
    log_views: float | None = None
    likes_per_view: float | None = None
    comments_per_view: float | None = None
    shares_per_view: float | None = None
    creator_key: str | None = None
    creator_baseline_log_views: float | None = None
    n_creator_other_videos: int | None = None
    expected_log_views_age_model: float | None = None

    # --- final labels (nullable) ---
    creator_relative_log_views: float | None = None
    performance_residual: float | None = None

    # --- validity ---
    is_valid: bool = False
    invalid_reasons: list[str] = field(default_factory=list)

    # --- provenance ---
    constructed_at: str | None = None
    code_revision: str | None = None
    construction_config: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)
