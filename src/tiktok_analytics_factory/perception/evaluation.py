"""Evaluation of detected boundaries against manual hard-cut annotations.

This is an evaluation of deterministic cut detection only, not a claim that
all semantic scene changes are hard cuts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_TOLERANCE_SECONDS = 0.30


@dataclass
class CutAnnotation:
    """A manually annotated hard visual cut."""

    timestamp_seconds: float


@dataclass
class BoundaryEvaluation:
    true_positives: int
    false_positives: int
    missed: int
    precision: float | None
    recall: float | None
    f1: float | None
    median_absolute_error_seconds: float | None
    tolerance_seconds: float
    matched_pairs: list[tuple[float, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "missed": self.missed,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "median_absolute_error_seconds": self.median_absolute_error_seconds,
            "tolerance_seconds": self.tolerance_seconds,
        }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def evaluate_boundaries(
    detected_timestamps: list[float],
    annotations: list[CutAnnotation],
    tolerance_seconds: float = DEFAULT_TOLERANCE_SECONDS,
) -> BoundaryEvaluation:
    """Greedy nearest-neighbor matching within a documented tolerance."""
    ann_times = sorted(a.timestamp_seconds for a in annotations)
    matched_pairs: list[tuple[float, float]] = []
    used_ann = set()

    for det in sorted(detected_timestamps):
        best_i, best_err = None, None
        for i, ann in enumerate(ann_times):
            if i in used_ann:
                continue
            err = abs(det - ann)
            if err <= tolerance_seconds and (best_err is None or err < best_err):
                best_i, best_err = i, err
        if best_i is not None:
            used_ann.add(best_i)
            matched_pairs.append((det, ann_times[best_i]))

    tp = len(matched_pairs)
    fp = len(detected_timestamps) - tp
    missed = len(ann_times) - tp

    def ratio(num: int, den: int) -> float | None:
        return num / den if den else None

    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + missed)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall)
        else None
    )
    errors = [abs(d - a) for d, a in matched_pairs]

    return BoundaryEvaluation(
        true_positives=tp,
        false_positives=fp,
        missed=missed,
        precision=precision,
        recall=recall,
        f1=f1,
        median_absolute_error_seconds=_median(errors),
        tolerance_seconds=tolerance_seconds,
        matched_pairs=matched_pairs,
    )


def shot_cut_timestamps(shot_boundaries: list[tuple[float, float]]) -> list[float]:
    """Internal cut timestamps from a shots list (start/end pairs).

    The first shot's start at 0 is not a cut; each subsequent start is.
    """
    starts = [s for s, _ in shot_boundaries]
    return [round(s, 6) for s in starts[1:] if s > 0]
