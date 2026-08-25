"""Versioned error taxonomy and severity levels for dataset QA.

Every human-reviewed or automatic quality label must use a category from
ERROR_TAXONOMY. The taxonomy is versioned; bump TAXONOMY_VERSION only when
categories are added/removed/renamed, never for cosmetic changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

TAXONOMY_VERSION = "1.0.0"

ERROR_TAXONOMY: frozenset[str] = frozenset(
    {
        "source_collection",
        "cohort_mismatch",
        "metadata_missing",
        "media_probe",
        "shot_boundary",
        "ocr_text",
        "spoken_dialogue",
        "visual_description",
        "camera_editing",
        "audio",
        "hook_narrative",
        "commercial_reasoning",
        "reconstruction",
        "schema_validation",
        "canonical_projection",
        "performance_snapshot",
        "provenance",
        "provider_failure",
        "other",
    }
)

SEVERITIES: frozenset[str] = frozenset({"minor", "material", "blocking"})


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ValidationIssue:
    """One deterministic validation finding."""

    category: str
    message: str
    severity: str = "material"
    field: str | None = None
    shot_id: str | None = None

    def __post_init__(self) -> None:
        if self.category not in ERROR_TAXONOMY:
            raise ValueError(f"unknown taxonomy category: {self.category!r}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid severity: {self.severity!r}")

    def to_dict(self) -> dict[str, Any]:
        out = {"category": self.category, "severity": self.severity, "message": self.message}
        if self.field is not None:
            out["field"] = self.field
        if self.shot_id is not None:
            out["shot_id"] = self.shot_id
        return out


@dataclass
class ReviewError:
    """A human-annotated quality/failure label on a record (or shot/field)."""

    category: str
    severity: str
    note: str = ""
    timestamp: str = field(default_factory=utcnow_iso)
    shot_id: str | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        if self.category not in ERROR_TAXONOMY:
            raise ValueError(
                f"review error category {self.category!r} not in taxonomy "
                f"v{TAXONOMY_VERSION}"
            )
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid severity: {self.severity!r}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewError":
        return cls(
            category=data["category"],
            severity=data["severity"],
            note=data.get("note", ""),
            timestamp=data.get("timestamp") or utcnow_iso(),
            shot_id=data.get("shot_id"),
            field=data.get("field"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "category": self.category,
            "severity": self.severity,
            "note": self.note,
            "timestamp": self.timestamp,
        }
        if self.shot_id is not None:
            out["shot_id"] = self.shot_id
        if self.field is not None:
            out["field"] = self.field
        return out


def validate_taxonomy_dict(data: dict[str, Any]) -> list[str]:
    """Validate an arbitrary serialized error payload against the taxonomy.

    Returns a list of problems (empty when valid).
    """
    problems: list[str] = []
    errors = data.get("errors", [])
    if not isinstance(errors, list):
        return ["'errors' must be a list"]
    for i, err in enumerate(errors):
        try:
            ReviewError.from_dict(err)
        except (KeyError, ValueError) as exc:
            problems.append(f"errors[{i}]: {exc}")
    return problems
