"""Tests for deterministic QA validators."""

from __future__ import annotations

import copy

import pytest

from tiktok_analytics_factory.qa.records import load_record
from tiktok_analytics_factory.qa.validators import run_validators
from tests.qa_fixtures import (
    build_record,
    good_creative_ir,
    good_performance,
    write_cohort_config,
)


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "dataset"
    build_record(root)
    write_cohort_config(root)
    return root


def _issues_by_category(record):
    return {i.category for i in run_validators(record)}


def test_good_record_passes_all_validators(dataset):
    record = load_record(dataset, "7300000000000000001")
    issues = run_validators(record)
    assert issues == [], [i.to_dict() for i in issues]


def test_mismatched_video_id_fails(dataset):
    rec_dir = build_record(
        dataset,
        "7300000000000000002",
        manifest={"video_id": "7300000000000000099"},
        creative_ir=good_creative_ir(),
        performance=good_performance(),
    )
    # creative_ir still points at the old id too
    record = load_record(dataset, "7300000000000000002")
    cats = _issues_by_category(record)
    assert "source_collection" in cats
    assert any("does not match" in i.message for i in run_validators(record))


def test_invalid_shot_timeline_fails(dataset):
    bad_perception = {
        "media": {"duration_s": 10.0, "width": 1080, "height": 1920, "fps": 30.0},
        "shots": [
            {"shot_id": "shot_001", "start_s": 2.0, "end_s": 1.0, "representative_frame": None},
            {"shot_id": "shot_002", "start_s": 0.0, "end_s": 5.0, "representative_frame": None},
            {"shot_id": "shot_002", "start_s": 1.0, "end_s": 12.0},
        ],
    }
    build_record(dataset, "7300000000000000003", perception=bad_perception)
    record = load_record(dataset, "7300000000000000003")
    issues = run_validators(record)
    shot_issues = [i for i in issues if i.category == "shot_boundary"]
    assert any("end <= start" in i.message for i in shot_issues)
    assert any("overlaps" in i.message for i in shot_issues)


def test_missing_representative_frame_flagged(dataset):
    bad = {
        "media": {"duration_s": 10.0, "width": 1080, "height": 1920, "fps": 30.0},
        "shots": [{"shot_id": "s1", "start_s": 0.0, "end_s": 10.0}],
    }
    build_record(dataset, "7300000000000000004", perception=bad)
    record = load_record(dataset, "7300000000000000004")
    issues = run_validators(record)
    assert any("missing representative_frame" in i.message for i in issues)


def test_invalid_creative_ir_schema_fails(dataset):
    bad_ir = good_creative_ir()
    bad_ir["shots"][0]["time_range"] = {"start_s": 5.0, "end_s": 1.0}
    del bad_ir["prompt_version"]
    bad_ir["shots"].append(copy.deepcopy(bad_ir["shots"][0]))
    build_record(dataset, "7300000000000000005", creative_ir=bad_ir)
    record = load_record(dataset, "7300000000000000005")
    issues = run_validators(record)
    msgs = [i.message for i in issues]
    assert any("invalid time range" in m for m in msgs)
    assert any("prompt_version" in m for m in msgs)
    assert any("duplicate CreativeIR shot_id" in m for m in msgs)


def test_unknown_inferred_reference_fails(dataset):
    bad_ir = good_creative_ir()
    bad_ir["shots"][0]["visual_description"]["inferred_from"] = [{"id": "nope"}]
    build_record(dataset, "7300000000000000006", creative_ir=bad_ir)
    record = load_record(dataset, "7300000000000000006")
    assert any("references unknown id" in i.message for i in run_validators(record))


def test_canonical_projection_mismatch_fails(dataset):
    tampered = {
        "schema_version": "0.1.0",
        "source_video_id": "7300000000000000007",
        "projection": {"schema_version": "0.1.0", "source_video_id": "x", "shots": []},
    }
    build_record(dataset, "7300000000000000007", canonical_ir=tampered)
    record = load_record(dataset, "7300000000000000007")
    issues = run_validators(record)
    assert any(i.category == "canonical_projection" and "projection" in i.message for i in issues)


def test_generation_prose_in_creative_ir_fails(dataset):
    bad_ir = good_creative_ir()
    bad_ir["generation"] = "Here is a fresh caption idea..."
    build_record(dataset, "7300000000000000008", creative_ir=bad_ir)
    record = load_record(dataset, "7300000000000000008")
    issues = run_validators(record)
    assert any("generation" in i.message for i in issues)


def test_performance_negative_metric_fails(dataset):
    perf = {
        "snapshots": [
            {"observed_at": "2026-02-01T00:00:00+00:00", "metrics": {"views": -5}}
        ]
    }
    build_record(dataset, "7300000000000000009", performance=perf)
    record = load_record(dataset, "7300000000000000009")
    issues = run_validators(record)
    assert any("negative metric" in i.message for i in issues)


def test_unordered_performance_snapshots_fail(dataset):
    perf = {
        "snapshots": [
            {"observed_at": "2026-02-02T00:00:00+00:00", "metrics": {"views": 10}},
            {"observed_at": "2026-02-01T00:00:00+00:00", "metrics": {"views": 20}},
        ]
    }
    build_record(dataset, "7300000000000000010", performance=perf)
    record = load_record(dataset, "7300000000000000010")
    assert any("not timestamp-ordered" in i.message for i in run_validators(record))


def test_cohort_mismatch_fails(dataset):
    build_record(dataset, "7300000000000000011", manifest={"cohort_id": "not-approved"})
    record = load_record(dataset, "7300000000000000011")
    issues = run_validators(record)
    assert any(i.category == "cohort_mismatch" for i in issues)


def test_observed_before_published_fails(dataset):
    build_record(
        dataset,
        "7300000000000000012",
        manifest={"observed_at": "2025-12-01T00:00:00+00:00"},
    )
    record = load_record(dataset, "7300000000000000012")
    issues = run_validators(record)
    assert any("earlier than published_at" in i.message for i in issues)


def test_target_validator_registration(dataset):
    from tiktok_analytics_factory.qa.taxonomy import ValidationIssue
    from tiktok_analytics_factory.qa import validators as V

    @V.register_target_validator
    def target_check(record):
        return [ValidationIssue("performance_snapshot", "target stub")] if record.performance else []

    try:
        record = load_record(dataset, "7300000000000000001")
        assert any("target stub" in i.message for i in run_validators(record))
    finally:
        V._VALIDATOR_REGISTRY.pop("derived_target", None)
