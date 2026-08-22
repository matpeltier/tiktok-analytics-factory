"""Boundary evaluation against manual hard-cut annotations."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median


@dataclass
class BoundaryEvaluation:
    true_positives: int = 0
    false_positives: int = 0
    missed: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    median_absolute_error_seconds: float | None = None
    matched_pairs: list[tuple[float, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "missed": self.missed,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "median_absolute_error_seconds": self.median_absolute_error_seconds,
        }


def evaluate_boundaries(
    detected_cuts: list[float],
    ground_truth_cuts: list[float],
    tolerance_seconds: float = 0.30,
) -> BoundaryEvaluation:
    """Greedy one-to-one matching of detected vs annotated cut times.

    A detected cut matches a ground-truth cut when the absolute difference is
    within ``tolerance_seconds`` (default +/- 0.30s). Each cut may be matched
    at most once on either side.
    """
    detected = sorted(detected_cuts)
    truth = sorted(ground_truth_cuts)
    used_truth: set[int] = set()
    matched_pairs: list[tuple[float, float]] = []
    errors: list[float] = []

    for det in detected:
        best_j, best_err = None, None
        for j, gt in enumerate(truth):
            if j in used_truth:
                continue
            err = abs(det - gt)
            if err <= tolerance_seconds and (best_err is None or err < best_err):
                best_j, best_err = j, err
        if best_j is not None:
            used_truth.add(best_j)
            matched_pairs.append((det, truth[best_j]))
            errors.append(best_err)

    tp = len(matched_pairs)
    fp = len(detected) - tp
    fn = len(truth) - tp
    precision = tp / len(detected) if detected else 0.0
    recall = tp / len(truth) if truth else 0.0
    f1 = (
        2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    )
    return BoundaryEvaluation(
        true_positives=tp,
        false_positives=fp,
        missed=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        median_absolute_error_seconds=round(median(errors), 6) if errors else None,
        matched_pairs=matched_pairs,
    )
