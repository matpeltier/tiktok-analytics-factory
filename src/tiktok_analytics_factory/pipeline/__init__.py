"""Batch pilot pipeline: cohort filtering, per-video processing, dataset index."""

from .cohort import CohortPolicy, CohortDecision, load_cohort
from .sources import SourceEntry, load_sources
from .runner import run_pilot, PilotSummary

__all__ = [
    "CohortPolicy",
    "CohortDecision",
    "load_cohort",
    "SourceEntry",
    "load_sources",
    "run_pilot",
    "PilotSummary",
]
