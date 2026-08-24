"""Cohort policy loading and inclusion decisions (issue #7 contract)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CohortDecision:
    """Explicit include/reject decision for one candidate source."""

    accepted: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "reason": self.reason}


@dataclass(frozen=True)
class CohortPolicy:
    """Versioned micro-niche cohort definition loaded from config JSON."""

    cohort_id: str
    version: str
    niche: str
    max_videos: int
    rules: dict[str, Any]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CohortPolicy:
        for key in ("cohort_id", "version"):
            if not payload.get(key):
                raise ValueError(f"cohort config missing required field: {key}")
        approval = payload.get("approval_status")
        if approval is not None and approval != "approved":
            raise ValueError(
                f"cohort config is not approved (approval_status={approval!r}); "
                "issue #8 requires an explicitly approved pilot_cohort.json"
            )
        # Shape 1: compact pilot config with a flat ``rules`` object.
        rules = payload.get("rules")
        if rules is None:
            # Shape 2: the full approved issue-#7 cohort schema.
            sampling = payload.get("pilot_sampling_policy") or {}
            size_range = sampling.get("target_size_range") or [1, 50]
            duration = payload.get("duration_seconds") or {}
            rules = {
                "required_hashtags": [],
                "min_duration_seconds": duration.get("min"),
                "max_duration_seconds": duration.get("max"),
                "max_videos_per_creator": sampling.get("max_videos_per_creator"),
                "performance_strata": sampling.get("performance_strata"),
            }
        niche = payload.get("niche") or payload.get("niche_name")
        if not niche:
            raise ValueError("cohort config missing required field: niche")
        max_videos = int(payload.get("max_videos") or max(int(size_range[1]), 1))
        if not 1 <= max_videos <= 50:
            raise ValueError("pilot cohort max_videos must be within 1..50")
        return cls(
            cohort_id=payload["cohort_id"],
            version=str(payload["version"]),
            niche=niche,
            max_videos=max_videos,
            rules=rules,
        )

    def check(self, entry: Any) -> CohortDecision:
        """Evaluate a SourceEntry against the policy.

        Rules supported (all optional, fail-closed when a required field is
        absent from the candidate): ``required_hashtags`` (any-of),
        ``allowed_creator_handles`` (empty means any), ``min_views`` /
        ``max_views`` for performance-level diversity enforcement.
        """
        tags = set(entry.hashtags or [])
        required = set(self.rules.get("required_hashtags", []))
        if required and not (tags & required):
            return CohortDecision(
                False,
                f"missing_required_hashtag: needs any of {sorted(required)}, has {sorted(tags)}",
            )
        allowed = self.rules.get("allowed_creator_handles")
        if allowed is not None:
            allowed_set = {h.lstrip("@").lower() for h in allowed}
            handle = (entry.creator_handle or "").lstrip("@").lower()
            if handle and handle not in allowed_set:
                return CohortDecision(False, f"creator_not_allowed: {handle}")
        min_views = self.rules.get("min_views")
        if min_views is not None and (entry.views is None or entry.views < int(min_views)):
            return CohortDecision(
                False, f"views_below_min: views={entry.views} < {min_views}"
            )
        max_views = self.rules.get("max_views")
        if max_views is not None and (entry.views is None or entry.views > int(max_views)):
            return CohortDecision(
                False, f"views_above_max: views={entry.views} > {max_views}"
            )
        return CohortDecision(True, "eligible")


def load_cohort(path: str | Path) -> CohortPolicy:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return CohortPolicy.from_dict(data)
