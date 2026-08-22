"""Tests for the pilot cohort config loader and validation."""

import json
from pathlib import Path

import pytest

from tiktok_analytics_factory import cohort

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "config" / "pilot_cohort.json"
SCHEMA = REPO_ROOT / "schemas" / "pilot_cohort.schema.json"


def test_config_and_schema_exist() -> None:
    assert CONFIG.exists()
    assert SCHEMA.exists()


def test_shipped_config_validates_against_schema() -> None:
    config = cohort.load_config(CONFIG)
    schema = cohort.load_schema(SCHEMA)
    cohort.validate_config(config, schema)


def test_single_micro_niche_frozen() -> None:
    config = json.loads(CONFIG.read_text())
    assert config["platform"] == "tiktok"
    # Exactly one niche: single cohort id, no multi-niche list.
    assert isinstance(config["cohort_id"], str)
    assert config["cohort_id"]


def test_duplicate_policy_is_explicit() -> None:
    config = json.loads(CONFIG.read_text())
    policy = config["duplicate_policy"]
    assert policy["same_video_id"] == "one_source_record"
    assert policy["near_duplicate_detection"] in {
        "manual_during_pilot",
        "automated",
        "none",
    }
    assert policy["direct_reposts"] != "treated_independent"


def test_performance_snapshot_requirements_are_mandatory() -> None:
    config = json.loads(CONFIG.read_text())
    perf = config["performance_observation_policy"]
    assert perf["store_published_at_when_available"] is True
    assert perf["store_observed_at_for_every_snapshot"] is True
    assert perf["store_creator_identity_when_available"] is True
    assert perf["store_follower_count_when_available"] is True
    assert perf["store_raw_metrics_unnormalized"] is True
    for metric in ("views", "likes", "comments", "shares"):
        assert metric in perf["raw_metrics"]


def test_sampling_does_not_allow_viral_only() -> None:
    config = json.loads(CONFIG.read_text())
    sampling = config["pilot_sampling_policy"]
    lo, hi = sampling["target_size_range"]
    assert 20 <= lo and hi <= 50
    assert sampling["viral_only_sampling_allowed"] is False
    assert sampling.get("max_videos_per_creator", 0) >= 1
    assert len(sampling["performance_strata"]) >= 2


def test_validation_fails_on_missing_required_field(tmp_path: Path) -> None:
    config = json.loads(CONFIG.read_text())
    del config["duplicate_policy"]
    with pytest.raises(cohort.CohortConfigError, match="duplicate_policy"):
        cohort.validate_config(config, cohort.load_schema(SCHEMA))


def test_validation_fails_on_bad_platform(tmp_path: Path) -> None:
    config = json.loads(CONFIG.read_text())
    config["platform"] = "instagram"
    with pytest.raises(cohort.CohortConfigError):
        cohort.validate_config(config, cohort.load_schema(SCHEMA))


def test_validation_fails_on_unapproved_sampling(tmp_path: Path) -> None:
    config = json.loads(CONFIG.read_text())
    config["pilot_sampling_policy"]["viral_only_sampling_allowed"] = True
    with pytest.raises(cohort.CohortConfigError):
        cohort.validate_config(config, cohort.load_schema(SCHEMA))


def test_require_approved_blocks_draft_cohort() -> None:
    config = cohort.load_validated_config(CONFIG, SCHEMA)
    if config["approval_status"] != "approved":
        with pytest.raises(cohort.CohortConfigError, match="owner-approved"):
            cohort.require_approved(config)
    else:
        cohort.require_approved(config)
