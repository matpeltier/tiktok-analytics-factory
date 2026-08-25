"""Derived performance targets (leakage-safe target construction).

Raw Performance snapshots are immutable; every derived target lives in a
separate versioned artifact that references its source snapshot.
"""

from .construct import (
    creator_baselines,
    creator_relative_log_views,
    deterministic_method_version,
    engagement_ratios,
    expected_log_views,
    fit_age_baseline,
    log1p_views,
    pairwise_label,
    performance_residual,
)
from .models import (
    TARGET_SCHEMA_VERSION,
    InvalidTargetError,
    PerformanceTargetRecord,
)

__all__ = [
    "TARGET_SCHEMA_VERSION",
    "InvalidTargetError",
    "PerformanceTargetRecord",
    "creator_baselines",
    "creator_relative_log_views",
    "deterministic_method_version",
    "engagement_ratios",
    "expected_log_views",
    "fit_age_baseline",
    "log1p_views",
    "pairwise_label",
    "performance_residual",
]
