"""Tests for the v0.1 data contracts: schemas, examples, projection."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from tiktok_analytics_factory.contracts.projection import (
    ProjectionError,
    project_creative_to_canonical,
    validate_against_schema,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = REPO_ROOT / "schemas"
EXAMPLES = REPO_ROOT / "examples"

SCHEMA_FILES = [
    "creative_ir_v0_1.json",
    "canonical_ir_v0_1.json",
    "performance_v0_1.json",
]


def load(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


@pytest.fixture(scope="module")
def schemas() -> dict[str, dict]:
    return {name: load(SCHEMAS / name) for name in SCHEMA_FILES}


@pytest.mark.parametrize("name", SCHEMA_FILES)
def test_schemas_are_valid_draft_2020_12(schemas, name):
    cls = jsonschema.validators.validator_for(schemas[name])
    assert cls is jsonschema.Draft202012Validator
    cls.check_schema(schemas[name])


@pytest.mark.parametrize(
    "example,schema",
    [
        ("creative_ir_v0_1_reference.json", "creative_ir_v0_1.json"),
        ("canonical_ir_v0_1_reference.json", "canonical_ir_v0_1.json"),
        ("performance_v0_1_reference.json", "performance_v0_1.json"),
    ],
)
def test_reference_examples_validate(example, schema):
    jsonschema.Draft202012Validator(load(SCHEMAS / schema)).validate(load(EXAMPLES / example))


def _base_performance() -> dict:
    return load(EXAMPLES / "performance_v0_1_reference.json")


class TestPerformanceSemantics:
    def test_unknown_is_null_not_zero(self):
        perf = _base_performance()
        assert perf["metrics"]["saves"] is None

    def test_zero_is_valid_observed_zero(self):
        perf = _base_performance()
        perf["metrics"]["saves"] = 0
        jsonschema.Draft202012Validator(load(SCHEMAS / "performance_v0_1.json")).validate(perf)

    def test_negative_metrics_rejected(self):
        validator = jsonschema.Draft202012Validator(load(SCHEMAS / "performance_v0_1.json"))
        perf = _base_performance()
        perf["metrics"]["views"] = -5
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(perf)

    def test_observed_at_must_be_iso_timestamp(self):
        validator = jsonschema.FormatChecker()
        cls = jsonschema.Draft202012Validator(
            load(SCHEMAS / "performance_v0_1.json"), format_checker=validator
        )
        perf = _base_performance()
        perf["observed_at"] = "not-a-timestamp"
        with pytest.raises(jsonschema.ValidationError):
            cls.validate(perf)

    def test_multiple_snapshots_representable_without_mutation(self):
        """Two snapshots of one video are two independent records."""
        s1, s2 = _base_performance(), _base_performance()
        s2["observed_at"] = "2026-02-01T00:00:00+00:00"
        s2["metrics"]["views"] = 20000
        assert s1["metrics"]["views"] == 15234  # untouched
        validator = jsonschema.Draft202012Validator(load(SCHEMAS / "performance_v0_1.json"))
        for snap in (s1, s2):
            validator.validate(snap)
        assert s1["video_id"] == s2["video_id"]

    def test_no_labels_or_ranker_outputs_allowed(self):
        validator = jsonschema.Draft202012Validator(load(SCHEMAS / "performance_v0_1.json"))
        perf = _base_performance()
        perf["virality_score"] = 0.9
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(perf)


class TestCreativeIRValidation:
    @pytest.fixture()
    def creative(self) -> dict:
        return load(EXAMPLES / "creative_ir_v0_1_reference.json")

    def _validate(self, creative: dict):
        jsonschema.Draft202012Validator(load(SCHEMAS / "creative_ir_v0_1.json")).validate(creative)

    def test_shot_ordering_enforced_by_test_convention(self, creative):
        starts = [s["start_seconds"] for s in creative["observed"]["shots"]]
        assert starts == sorted(starts)
        for shot in creative["observed"]["shots"]:
            assert shot["end_seconds"] > shot["start_seconds"]

    def test_inverted_shot_times_are_structurally_possible_but_flagged(self, creative):
        """Schema-level guard: end <= start must be caught by projection validation."""
        bad = copy.deepcopy(creative)
        bad["observed"]["shots"][0]["end_seconds"] = bad["observed"]["shots"][0]["start_seconds"]
        with pytest.raises(ProjectionError, match="shot ordering"):
            project_creative_to_canonical(bad, projected_at="2026-01-02T10:05:00+00:00")

    def test_invalid_annotation_mode_rejected(self, creative):
        bad = copy.deepcopy(creative)
        bad["decompilation"]["annotation_mode"] = "psychic"
        with pytest.raises(jsonschema.ValidationError):
            self._validate(bad)

    def test_invalid_confidence_enum_rejected(self, creative):
        bad = copy.deepcopy(creative)
        bad["inferred"]["overall_concept"]["confidence"] = "certain"
        with pytest.raises(jsonschema.ValidationError):
            self._validate(bad)

    def test_vendor_generation_fields_forbidden(self, creative):
        bad = copy.deepcopy(creative)
        bad["generation"]["higgsfield_prompt"] = "cinematic..."
        with pytest.raises(jsonschema.ValidationError):
            self._validate(bad)

    def test_non_commercial_uses_explicit_status(self, creative):
        assert creative["inferred"]["commercial_interpretation"]["status"] == "non_commercial"
        assert creative["inferred"]["commercial_interpretation"]["cta_text"] is None


SYNTHETIC_COMMERCIAL_CREATIVE = {
    "schema_version": "0.1",
    "source": {
        "platform": "tiktok",
        "video_id": "9990000000000000001",
        "source_url": None,
        "creator_handle": "gadgetguy",
        "caption": "This gadget changed my mornings #ad #affiliate",
        "hashtags": ["ad", "affiliate"],
        "duration_seconds": 30.0,
        "published_at": "2026-01-01T08:00:00+00:00",
        "ingested_at": "2026-01-02T09:00:00+00:00",
        "artifact_hash_or_manifest": "sha256:synthetic",
    },
    "decompilation": {
        "schema_version": "0.1",
        "pipeline_version": "0.1.0",
        "model_id": "test-model",
        "provider": "test",
        "prompt_version": "v0",
        "created_at": "2026-01-02T09:00:00+00:00",
        "annotation_mode": "automated",
        "notes": None,
    },
    "observed": {
        "media_summary": "Presenter demonstrates a mug warmer.",
        "hook_evidence": {"description": "cold coffee complaint", "start_seconds": 0.0},
        "narrative_evidence": None,
        "marketing_evidence": {"description": "discount code shown", "evidence_refs": ["ocr:shot-02"]},
        "shots": [
            {
                "shot_id": "shot-01",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "subjects_and_actions": [
                    {"subject": "presenter", "action": "complains about cold coffee", "subject_category": "person"},
                    {"subject": "mug warmer", "action": "shown in box", "subject_category": "product"},
                ],
                "visual_description": "Kitchen counter.",
                "framing_shot_scale": "medium",
                "camera_movement": "handheld",
                "on_screen_text": [],
                "spoken_dialogue": [{"text": "my coffee is always cold", "certainty": "exact"}],
                "audio": [],
                "editing_transition_in": None,
                "evidence": [],
            },
            {
                "shot_id": "shot-02",
                "start_seconds": 10.0,
                "end_seconds": 30.0,
                "subjects_and_actions": [
                    {"subject": "mug warmer", "action": "heats mug", "subject_category": "product"}
                ],
                "visual_description": "Product demo close-up.",
                "framing_shot_scale": "close_up",
                "camera_movement": "static",
                "on_screen_text": [{"text": "link in bio - 20% off", "certainty": "exact"}],
                "spoken_dialogue": [],
                "audio": [],
                "editing_transition_in": "cut",
                "evidence": [],
            },
        ],
    },
    "inferred": {
        "overall_concept": {"statement": "Problem-solution affiliate demo.", "confidence": "high"},
        "target_audience_hypothesis": None,
        "hook": {"type": "problem_statement", "mechanism": None, "timing_seconds": 0.0, "confidence": "high"},
        "narrative_structure": {"structure": "problem_solution", "confidence": "high"},
        "attention_mechanisms": [],
        "marketing_persuasion_mechanisms": [
            {"mechanism": "discount urgency", "category": "urgency", "confidence": "high"}
        ],
        "commercial_interpretation": {
            "status": "commercial",
            "product_presence": "central",
            "first_product_appearance_seconds": 3.0,
            "problem_or_desire": "Cold coffee",
            "promise_or_claim": "Keeps coffee hot all morning",
            "proof_type": "demonstration",
            "trust_signals": ["on-camera demo"],
            "objections_addressed": ["price"],
            "offer": "20% off via link in bio",
            "cta_text": "link in bio",
            "cta_type": "link_in_bio",
            "confidence": "high",
        },
    },
}


class TestCanonicalIRConstraints:
    def test_generation_block_cannot_appear(self):
        validator = jsonschema.Draft202012Validator(load(SCHEMAS / "canonical_ir_v0_1.json"))
        canonical = load(EXAMPLES / "canonical_ir_v0_1_reference.json")
        canonical["generation"] = {"global_brief": "reconstruct everything"}
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(canonical)

    def test_raw_performance_cannot_appear_inside_canonical(self):
        validator = jsonschema.Draft202012Validator(load(SCHEMAS / "canonical_ir_v0_1.json"))
        canonical = load(EXAMPLES / "canonical_ir_v0_1_reference.json")
        canonical["views"] = 15234
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(canonical)

    def test_synthetic_commercial_branch_projects_and_validates(self):
        result = project_creative_to_canonical(
            SYNTHETIC_COMMERCIAL_CREATIVE, projected_at="2026-01-03T00:00:00+00:00"
        )
        assert result["inferred"]["commercial_status"] == "commercial"
        assert result["inferred"]["cta_type"] == "link_in_bio"
        assert result["inferred"]["proof_type"] == "demonstration"
        assert result["observed"]["first_product_appearance_seconds"] == 3.0


class TestProjectionDeterminism:
    def test_same_input_same_output(self):
        creative = load(EXAMPLES / "creative_ir_v0_1_reference.json")
        a = project_creative_to_canonical(creative, projected_at="2026-01-02T10:05:00+00:00")
        b = project_creative_to_canonical(copy.deepcopy(creative), projected_at="2026-01-02T10:05:00+00:00")
        assert a == b

    def test_projection_matches_reference_example(self):
        creative = load(EXAMPLES / "creative_ir_v0_1_reference.json")
        expected = load(EXAMPLES / "canonical_ir_v0_1_reference.json")
        result = project_creative_to_canonical(creative, projected_at=expected["projected_at"])
        assert result == expected

    def test_projection_output_validates_canonical_schema(self):
        creative = load(EXAMPLES / "creative_ir_v0_1_reference.json")
        result = project_creative_to_canonical(creative, projected_at="2026-01-02T10:05:00+00:00")
        jsonschema.Draft202012Validator(load(SCHEMAS / "canonical_ir_v0_1.json")).validate(result)

    def test_invalid_creative_fails_loudly(self):
        bad = {"schema_version": "0.1"}
        with pytest.raises(ProjectionError, match="schema validation failed"):
            project_creative_to_canonical(bad, projected_at="2026-01-02T10:05:00+00:00")

    def test_no_extra_blob_in_projection(self):
        creative = load(EXAMPLES / "creative_ir_v0_1_reference.json")
        result = project_creative_to_canonical(creative, projected_at="2026-01-02T10:05:00+00:00")
        assert "extra" not in result
        assert "extra" not in result["observed"]
        assert "generation" not in result
