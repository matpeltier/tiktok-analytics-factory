"""Dataset QA, human review, and audit tooling.

Public entry points:
  - ``python -m tiktok_analytics_factory.qa audit --dataset-root ... --output ...``
  - ``python -m tiktok_analytics_factory.qa review-app --dataset-root ...``
"""

from .taxonomy import (
    ERROR_TAXONOMY,
    SEVERITIES,
    TAXONOMY_VERSION,
    ReviewError,
    ValidationIssue,
)
from .reviews import REVIEW_FORMAT_VERSION
from .records import DatasetRecord, canonical_json, load_record, load_all_records, list_video_ids
from .validators import run_validators, register_validator, register_target_validator
from .reviews import Review, review_for_record, aggregate_reviews

__all__ = [
    "ERROR_TAXONOMY",
    "SEVERITIES",
    "TAXONOMY_VERSION",
    "REVIEW_FORMAT_VERSION",
    "ReviewError",
    "ValidationIssue",
    "DatasetRecord",
    "canonical_json",
    "load_record",
    "load_all_records",
    "list_video_ids",
    "run_validators",
    "register_validator",
    "register_target_validator",
    "Review",
    "review_for_record",
    "aggregate_reviews",
]
