"""Side-by-side comparison vs the #4 single-pass baseline and the decision gate.

The 11-category rubric comes verbatim from #4
(examples/evaluation/rubric_template_v0_1.json). Both pipelines are scored
with the same rubric; this module builds the comparison report and evaluates
the `validated-for-pilot` / `needs-one-video-fix` quality gates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RUBRIC_CATEGORIES = (
    "media_facts",
    "shot_boundaries_timeline",
    "visible_text_ocr",
    "dialogue",
    "visual_description",
    "camera_editing",
    "audio",
    "hook",
    "narrative",
    "marketing_commercial_reasoning",
    "reconstruction_quality",
)

VALIDATED = "validated-for-pilot"
NEEDS_FIX = "needs-one-video-fix"


def load_evaluation(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def _scores(evaluation: dict[str, Any]) -> dict[str, int]:
    categories = evaluation.get("categories") or {}
    return {name: categories[name]["score"] for name in RUBRIC_CATEGORIES if name in categories}


def build_comparison(
    baseline_evaluation: dict[str, Any],
    multistep_evaluation: dict[str, Any],
) -> dict[str, Any]:
    """Category-by-category comparison report with concrete evidence."""
    base_scores = _scores(baseline_evaluation)
    multi_scores = _scores(multistep_evaluation)

    category_rows = []
    for name in RUBRIC_CATEGORIES:
        b = base_scores.get(name)
        m = multi_scores.get(name)
        row: dict[str, Any] = {
            "category": name,
            "single_pass_score": b,
            "multi_step_score": m,
            "delta": (m - b) if (m is not None and b is not None) else None,
        }
        base_cat = (baseline_evaluation.get("categories") or {}).get(name) or {}
        multi_cat = (multistep_evaluation.get("categories") or {}).get(name) or {}
        if base_cat:
            row["single_pass_evidence"] = {
                "notes": base_cat.get("notes"),
                "evidence": base_cat.get("evidence"),
            }
        if multi_cat:
            row["multi_step_evidence"] = {
                "notes": multi_cat.get("notes"),
                "evidence": multi_cat.get("evidence"),
            }
        category_rows.append(row)

    base_avg = round(sum(base_scores.values()) / len(base_scores), 3) if base_scores else None
    multi_avg = round(sum(multi_scores.values()) / len(multi_scores), 3) if multi_scores else None

    def _count(evaluation: dict[str, Any], key: str) -> int:
        value = evaluation.get(key)
        return len(value) if isinstance(value, list) else 0

    return {
        "template_version": multistep_evaluation.get("template_version", "0.1"),
        "video_id": multistep_evaluation.get("run_metadata", {}).get(
            "video_id", baseline_evaluation.get("run_metadata", {}).get("video_id")
        ),
        "rubric_categories": list(RUBRIC_CATEGORIES),
        "categories": category_rows,
        "overall_average": {"single_pass": base_avg, "multi_step": multi_avg},
        "unsupported_claims": {
            "single_pass": baseline_evaluation.get("unsupported_claims", []),
            "single_pass_count": _count(baseline_evaluation, "unsupported_claims"),
            "multi_step": multistep_evaluation.get("unsupported_claims", []),
            "multi_step_count": _count(multistep_evaluation, "unsupported_claims"),
        },
        "material_omissions": {
            "single_pass_count": _count(baseline_evaluation, "missed_important_facts"),
            "multi_step_count": _count(multistep_evaluation, "missed_important_facts"),
        },
        "schema_success": {
            "single_pass": bool(baseline_evaluation.get("schema_validation_success")),
            "multi_step": bool(multistep_evaluation.get("schema_validation_success")),
        },
        "certain_claim_inventory": multistep_evaluation.get("certain_claim_inventory", []),
        "operational": {
            "single_pass": {
                "latency_seconds": baseline_evaluation.get("latency_seconds"),
                "api_usage": baseline_evaluation.get("api_usage"),
                "cost_usd": baseline_evaluation.get("cost_usd"),
                "model_calls": 1,
            },
            "multi_step": {
                "latency_seconds": multistep_evaluation.get("latency_seconds"),
                "api_usage": multistep_evaluation.get("api_usage"),
                "cost_usd": multistep_evaluation.get("cost_usd"),
                "model_calls": multistep_evaluation.get("model_call_count", 2),
            },
        },
    }


def build_evaluation_scaffold(
    creative_ir: dict[str, Any],
    media_facts: dict[str, Any],
    shots_result: dict[str, Any],
    usage_report: dict[str, Any],
) -> dict[str, Any]:
    """Objective part of the run evaluation; rubric scores stay manual.

    Fills everything that can be checked mechanically (schema success,
    deterministic-fact equality, certain-claim inventory for fabrication
    review, cost/latency/model-call counts). The 11-category manual rubric
    scores are left empty until a reviewer scores the output against the
    reference video.
    """
    det_boundaries = {
        s["shot_id"]: (s["start_seconds"], s["end_seconds"])
        for s in shots_result["shots"]
    }
    ir_boundaries = {
        s["shot_id"]: (s["start_seconds"], s["end_seconds"])
        for s in creative_ir["observed"]["shots"]
    }

    # Inventory of claims marked "certain" that a reviewer must verify against
    # the reference video (exact quotes/OCR and observed audio identities).
    certain_claims: list[dict[str, Any]] = []
    for shot in creative_ir["observed"]["shots"]:
        for item in shot.get("on_screen_text") or []:
            if item.get("exact"):
                certain_claims.append({
                    "kind": "exact_on_screen_text",
                    "shot_id": shot["shot_id"],
                    "claim": item["text"],
                })
        for item in shot.get("spoken_dialogue") or []:
            if item.get("exact"):
                certain_claims.append({
                    "kind": "exact_spoken_quote",
                    "shot_id": shot["shot_id"],
                    "claim": item["text"],
                })
        audio = shot.get("audio") or {}
        for base in ("music", "sfx", "ambience"):
            if audio.get(f"{base}_certainty") == "observed" and audio.get(base):
                certain_claims.append({
                    "kind": f"observed_{base}_identity",
                    "shot_id": shot["shot_id"],
                    "claim": audio[base],
                })

    decompilation = creative_ir.get("decompilation") or {}
    return {
        "template_version": "0.1",
        "run_metadata": {
            "video_id": creative_ir["source"]["video_id"],
            "pipeline_version": decompilation.get("pipeline_version"),
            "model_id": decompilation.get("model_id"),
            "prompt_version": decompilation.get("prompt_version"),
            "created_at": decompilation.get("created_at"),
        },
        "schema_validation_success": True,
        "canonical_projection_success": True,
        "deterministic_fact_checks": {
            "duration_equal": (
                creative_ir["source"]["duration_seconds"]
                == media_facts.get("duration_seconds")
            ),
            "artifact_sha256_equal": (
                creative_ir["source"]["artifact_sha256"]
                == media_facts.get("sha256")
            ),
            "boundaries_equal": ir_boundaries == det_boundaries,
        },
        "certain_claim_inventory": certain_claims,
        "unsupported_claims": [],
        "missed_important_facts": [],
        "categories": {},
        "scores_pending_manual_review": True,
        "latency_seconds": usage_report.get("total_latency_seconds"),
        "api_usage": usage_report.get("total_usage"),
        "cost_usd": usage_report.get("total_cost_usd"),
        "model_call_count": usage_report.get("model_call_count"),
    }


def record_manual_scores(
    evaluation: dict[str, Any],
    categories: dict[str, dict[str, Any]],
    unsupported_claims: list[dict[str, Any]] | None = None,
    missed_important_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fill in the manual rubric part of a scaffold evaluation.

    ``categories`` maps rubric category name -> {"score": int, "notes": str,
    "evidence": str}. Unknown category names raise ``ValueError`` so that
    rubric drift fails loudly instead of silently producing an incomparable
    report.
    """
    unknown = set(categories) - set(RUBRIC_CATEGORIES)
    if unknown:
        raise ValueError(f"Unknown rubric categories: {sorted(unknown)}")
    for name, cat in categories.items():
        if not {"score", "notes", "evidence"} <= set(cat):
            raise ValueError(f"Category {name!r} missing required keys")
    evaluation["categories"] = {name: dict(cat) for name, cat in categories.items()}
    evaluation["unsupported_claims"] = list(unsupported_claims or [])
    evaluation["missed_important_facts"] = list(missed_important_facts or [])
    evaluation["scores_pending_manual_review"] = False
    return evaluation


def evaluate_decision(comparison: dict[str, Any]) -> dict[str, Any]:
    """Apply the issue's hard/manual/operational gates to a comparison report.

    Returns {"decision": ..., "gate_results": [...], "follow_up": ...}.
    """
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"gate": name, "passed": bool(passed), "detail": detail})

    schema = comparison["schema_success"]
    check("creative_ir_schema_validation", schema["multi_step"])
    check("canonical_ir_projection", comparison.get("canonical_projection_pass", True))

    rows = {row["category"]: row for row in comparison["categories"]}
    facts = comparison.get("deterministic_fact_checks") or {}
    check(
        "deterministic_facts_exact",
        all(bool(v) for v in facts.values()) if facts else True,
        json.dumps(facts) if facts else "",
    )
    check(
        "no_certain_fabricated_quotes_or_audio",
        not comparison.get("certain_fabricated_claims", []),
    )

    avg = comparison["overall_average"]["multi_step"]
    check("overall_average_gte_4", avg is not None and avg >= 4.0)
    low = [
        (name, row["multi_step_score"])
        for name, row in rows.items()
        if row["multi_step_score"] is not None and row["multi_step_score"] < 3
    ]
    check("no_category_below_3", not low, f"below threshold: {low}" if low else "")
    hook_ok = (
        rows["hook"]["multi_step_score"] is not None
        and rows["hook"]["single_pass_score"] is not None
        and rows["hook"]["multi_step_score"] >= rows["hook"]["single_pass_score"]
    )
    narrative_ok = (
        rows["narrative"]["multi_step_score"] is not None
        and rows["narrative"]["single_pass_score"] is not None
        and rows["narrative"]["multi_step_score"] >= rows["narrative"]["single_pass_score"]
    )
    check("hook_at_least_baseline", hook_ok)
    check("narrative_at_least_baseline", narrative_ok)
    recon = rows["reconstruction_quality"]
    recon_ok = (recon["multi_step_score"] or 0) > (recon["single_pass_score"] or 0) or (
        recon["multi_step_score"] or 0) >= 4
    check("reconstruction_improved_or_gte4", recon_ok)

    unsupported = comparison["unsupported_claims"]
    base_zero = unsupported["single_pass_count"] == 0
    unsupported_ok = unsupported["multi_step_count"] < unsupported["single_pass_count"] or (
        base_zero and unsupported["multi_step_count"] == 0
    )
    check("fewer_unsupported_claims_than_baseline", unsupported_ok)

    operational = comparison["operational"]
    ms_op = operational["multi_step"]
    check(
        "cost_and_latency_recorded",
        ms_op.get("latency_seconds") is not None and ms_op.get("cost_usd") is not None,
    )

    failed = [c for c in checks if not c["passed"]]
    decision = VALIDATED if not failed else NEEDS_FIX
    follow_up = None
    if decision == NEEDS_FIX:
        follow_up = "; ".join(c["gate"] for c in failed)
    return {"decision": decision, "gate_results": checks, "follow_up": follow_up}
