"""Contract validation and projection tests for CreativeIR/CanonicalIR/Performance v0.1."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tiktok_analytics_factory.contracts import (
    ContractValidationError,
    build_performance_snapshot,
    load_schema,
    project_creative_to_canonical,
    validate,
    validator_for,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"

SCHEMA_FILES = {
    "creative_ir_v0_1": "creative_ir_v0_1.json",
    "canonical_ir_v0_1": "canonical_ir_v0_1.json",
    "performance_v0_1": "performance_v0_1.json",
}


@pytest.fixture(scope="module")
def creative_ref() -> dict:
    return json.loads((EXAMPLES / "creative_ir_v0_1_reference.json").read_text())


@pytest.fixture(scope="module")
def performance_ref() -> dict:
    return json.loads((EXAMPLES / "performance_v0_1_reference.json").read_text())


# --- schemas are valid Draft 2020-12 --------------------------------------


def test_schemas_are_valid_draft_2020_12():
    for name, filename in SCHEMA_FILES.items():
        schema = load_schema(name)
        assert schema["$schema"].endswith("2020-12/schema")
        cls = validator_for(name)
        cls.check_schema(schema)


# --- reference examples validate ------------------------------------------


def test_creative_reference_validates(creative_ref):
    validate(creative_ref, "creative_ir_v0_1")


def test_canonical_reference_validates():
    example = json.loads((EXAMPLES / "canonical_ir_v0_1_reference.json").read_text())
    validate(example, "canonical_ir_v0_1")


def test_performance_reference_validates(performance_ref):
    validate(performance_ref, "performance_v0_1")


# --- malformed timestamps / ordering rejected -----------------------------


def test_invalid_timestamp_rejected(creative_ref):
    bad = copy.deepcopy(creative_ref)
    bad["decompilation"]["created_at"] = "not-a-timestamp"
    with pytest.raises(ContractValidationError):
        validate(bad, "creative_ir_v0_1")


def test_shot_end_before_start_rejected(creative_ref):
    bad = copy.deepcopy(creative_ref)
    bad["observed"]["shots"][0]["start_seconds"] = 9.0
    bad["observed"]["shots"][0]["end_seconds"] = 8.0
    with pytest.raises(ContractValidationError):
        validate(bad, "creative_ir_v0_1")


def test_negative_shot_start_rejected(creative_ref):
    bad = copy.deepcopy(creative_ref)
    bad["observed"]["shots"][0]["start_seconds"] = -1.0
    with pytest.raises(ContractValidationError):
        validate(bad, "creative_ir_v0_1")


def test_performance_observed_at_must_be_valid(performance_ref):
    bad = copy.deepcopy(performance_ref)
    bad["observed_at"] = "22/08/2026"
    with pytest.raises((ContractValidationError, ValueError)):
        build_performance_snapshot(
            video_id=bad["video_id"],
            source_url=bad.get("source_url"),
            creator_handle=bad.get("creator_handle"),
            creator_id=bad.get("creator_id"),
            published_at=bad.get("published_at"),
            observed_at=bad["observed_at"],
            metrics=bad["metrics"],
            follower_count_at_observation=bad.get("follower_count_at_observation"),
            collector=bad["collector"],
        )


def test_published_after_observed_rejected(performance_ref):
    base = dict(
        video_id="7300000000000000001",
        source_url=None,
        creator_handle=None,
        creator_id=None,
        observed_at="2026-08-22T12:00:00+00:00",
        metrics={"views": 1},
        follower_count_at_observation=None,
        collector={"name": "x", "collected_at": "2026-08-22T12:00:00+00:00"},
    )
    # equal timestamps are allowed (age 0)
    ok = build_performance_snapshot(published_at="2026-08-22T12:00:00+00:00", **base)
    assert ok["age_since_publish_seconds"] == 0
    # published after observed is rejected
    with pytest.raises(ContractValidationError):
        build_performance_snapshot(published_at="2030-01-01T00:00:00+00:00", **base)


# --- invalid enum values rejected ------------------------------------------


def test_invalid_hook_type_enum_rejected(creative_ref):
    bad = copy.deepcopy(creative_ref)
    bad["inferred"]["hook_type"]["value"] = "super_hook"
    with pytest.raises(ContractValidationError):
        validate(bad, "creative_ir_v0_1")


def test_invalid_confidence_enum_rejected(creative_ref):
    bad = copy.deepcopy(creative_ref)
    bad["inferred"]["concept"]["confidence"] = "certain"
    with pytest.raises(ContractValidationError):
        validate(bad, "creative_ir_v0_1")


def test_invalid_annotation_mode_rejected(creative_ref):
    bad = copy.deepcopy(creative_ref)
    bad["decompilation"]["annotation_mode"] = "psychic"
    with pytest.raises(ContractValidationError):
        validate(bad, "creative_ir_v0_1")


def test_non_commercial_with_details_rejected(creative_ref):
    bad = copy.deepcopy(creative_ref)
    bad["inferred"]["commercial"]["details"] = {"product_presence": "bread"}
    with pytest.raises(ContractValidationError):
        validate(bad, "creative_ir_v0_1")


def test_commercial_requires_details(creative_ref):
    bad = copy.deepcopy(creative_ref)
    bad["inferred"]["commercial"] = {"status": "commercial"}
    with pytest.raises(ContractValidationError):
        validate(bad, "creative_ir_v0_1")


# --- unknown vs zero semantics in Performance ------------------------------


def test_unknown_vs_zero_metrics_preserved():
    snap = build_performance_snapshot(
        video_id="v1",
        source_url=None,
        creator_handle=None,
        creator_id=None,
        published_at=None,
        observed_at="2026-08-22T12:00:00+00:00",
        metrics={"views": 0, "likes": None},
        follower_count_at_observation=None,
        collector={"name": "x", "collected_at": "2026-08-22T12:00:00+00:00"},
    )
    assert snap["metrics"]["views"] == 0  # observed zero
    assert snap["metrics"]["likes"] is None  # unknown
    assert snap["metrics"]["saves"] is None  # missing => unknown, not zero
    assert snap["age_since_publish_seconds"] is None


def test_negative_metric_rejected():
    with pytest.raises(ContractValidationError):
        build_performance_snapshot(
            video_id="v1",
            source_url=None,
            creator_handle=None,
            creator_id=None,
            published_at=None,
            observed_at="2026-08-22T12:00:00+00:00",
            metrics={"views": -5},
            follower_count_at_observation=None,
            collector={"name": "x", "collected_at": "2026-08-22T12:00:00+00:00"},
        )


def test_multiple_snapshots_representable_without_mutation():
    """Same video at two observation times yields two independent records."""
    kwargs = dict(
        video_id="v1",
        source_url="https://www.tiktok.com/@a/video/v1",
        creator_handle="a",
        creator_id=None,
        published_at="2026-08-01T00:00:00+00:00",
        metrics={"views": 10},
        follower_count_at_observation=None,
        collector={"name": "x", "collected_at": "2026-08-22T12:00:00+00:00"},
    )
    s1 = build_performance_snapshot(observed_at="2026-08-02T00:00:00+00:00", **kwargs)
    s2_kwargs = {**kwargs, "metrics": {"views": 500}}
    s2 = build_performance_snapshot(observed_at="2026-08-03T00:00:00+00:00", **s2_kwargs)
    assert s1["metrics"]["views"] == 10
    assert s2["metrics"]["views"] == 500
    assert s1["observed_at"] != s2["observed_at"]
    assert s2["age_since_publish_seconds"] > s1["age_since_publish_seconds"]


# --- separation rules -------------------------------------------------------


def test_generation_block_cannot_appear_in_canonical_ir(creative_ref):
    projected = project_creative_to_canonical(creative_ref)
    assert "generation" not in projected
    smuggled = copy.deepcopy(projected)
    smuggled["generation"] = {"global_brief": "vendor prose"}
    with pytest.raises(ContractValidationError):
        validate(smuggled, "canonical_ir_v0_1")


def test_long_prose_dropped_from_projection(creative_ref):
    projected = project_creative_to_canonical(creative_ref)
    blob = json.dumps(projected)
    assert "reconstruction_intent" not in blob
    assert "global_brief" not in blob
    assert len(blob) < len(json.dumps(creative_ref)) / 2


def test_raw_performance_cannot_appear_inside_canonical_features(creative_ref):
    smuggled = copy.deepcopy(creative_ref)
    smuggled["observed"]["views"] = 15234
    with pytest.raises(ContractValidationError):
        validate(smuggled, "creative_ir_v0_1")


def test_performance_has_no_derived_labels(performance_ref):
    blob = json.dumps(performance_ref)
    for forbidden in ("virality_score", "residual", "label", "rank"):
        assert forbidden not in blob


# --- deterministic projection ------------------------------------------------


def test_projection_is_deterministic_and_validates(creative_ref):
    a = project_creative_to_canonical(creative_ref)
    b = project_creative_to_canonical(copy.deepcopy(creative_ref))
    assert a == b
    validate(a, "canonical_ir_v0_1")


def test_projection_matches_committed_reference_example(creative_ref):
    committed = json.loads((EXAMPLES / "canonical_ir_v0_1_reference.json").read_text())
    assert project_creative_to_canonical(creative_ref) == committed


# --- synthetic commercial fixture (reference video is non-commercial) -------


@pytest.fixture(scope="module")
def commercial_creative(creative_ref) -> dict:
    fixture = copy.deepcopy(creative_ref)
    fixture["source"]["video_id"] = "synthetic-commercial-001"
    fixture["observed"]["marketing_evidence"] = "Bottle shown; spoken brand name."
    fixture["observed"]["first_product_appearance_seconds"] = 3.0
    fixture["inferred"]["hook_type"]["value"] = "problem_statement"
    fixture["inferred"]["narrative_structure"]["value"] = "problem_solution"
    fixture["inferred"]["commercial"] = {
        "status": "commercial",
        "details": {
            "product_presence": "Hydration drink bottle held by creator",
            "first_product_appearance_seconds": 3.0,
            "problem_desire": "Afternoon energy slump",
            "promise_claim": "Clean energy without the crash",
            "proof_type": "demonstration",
            "trust_signals": ["clinically tested"],
            "objections": ["too expensive"],
            "offer": "20% off first order via bio link",
            "cta": {"text": "link in bio", "text_exact": True, "type": "affiliate_link"},
        },
    }
    fixture.pop("generation")
    return fixture


def test_synthetic_commercial_branch_projects(commercial_creative):
    out = project_creative_to_canonical(commercial_creative)
    f = out["features"]
    assert f["commercial_status"] == "commercial"
    assert f["product_present"] is True
    assert f["first_product_appearance_seconds"] == 3.0
    assert f["cta_type"] == "affiliate_link"
    assert f["proof_labels"] == ["demonstration"]
    assert f["trust_labels"] == ["clinically tested"]
    validate(out, "canonical_ir_v0_1")


def test_uncertain_commercial_keeps_null_semantics(commercial_creative):
    fixture = copy.deepcopy(commercial_creative)
    fixture["inferred"]["commercial"] = {"status": "uncertain", "details": None}
    f = project_creative_to_canonical(fixture)["features"]
    assert f["product_present"] is None
    assert f["cta_type"] is None


def test_single_public_projection_entrypoint_produces_valid_canonical(creative_ref):
    import tiktok_analytics_factory.contracts as contracts_mod

    entrypoints = [
        name
        for name in dir(contracts_mod)
        if "project" in name.lower()
        and callable(getattr(contracts_mod, name))
        and not name.startswith("_")
    ]
    assert entrypoints == ["project_creative_to_canonical"]
    out = contracts_mod.project_creative_to_canonical(creative_ref)
    validate(out, "canonical_ir_v0_1")
