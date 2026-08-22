"""Tests for the single-pass baseline (request, parsing, validation, persistence)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tiktok_analytics_factory.baseline.artifacts import (
    RunArtifacts,
    new_run_id,
    run_directory,
    sha256_bytes,
)
from tiktok_analytics_factory.baseline.config import (
    BaselineConfig,
    BaselineConfigError,
    load_baseline_config,
)
from tiktok_analytics_factory.baseline.parsing import ParseError, parse_model_output, validate_against_schema
from tiktok_analytics_factory.baseline.request import (
    RequestBuildError,
    build_generation_settings,
    build_request_contents,
    render_prompt,
)

SCHEMA_PATH = Path("schemas/creative_ir_v0_1.schema.json")
PROMPT_PATH = Path("prompts/single_pass_creative_ir_v0_1.txt")


def make_config(tmp_path: Path) -> BaselineConfig:
    return BaselineConfig(
        provider="google",
        model_id="gemini-test-model",
        temperature=0.3,
        prompt_path=PROMPT_PATH,
        schema_path=SCHEMA_PATH,
        derived_root=tmp_path / "derived",
    )


def valid_ir() -> dict:
    return {
        "schema_version": "0.1",
        "source": {"video_id": "vid1", "duration_seconds_claimed": 21.3},
        "observed": {
            "timeline": [
                {
                    "index": 0,
                    "start_seconds": 0,
                    "end_seconds": 2.5,
                    "boundary_confidence": "high",
                    "description": "Close-up of a runner tying shoes",
                }
            ],
            "visible_text": [{"text": "STOP DOING THIS", "timestamp_seconds": 0.4}],
            "dialogue": [],
            "visual": {"overall_description": "Running-shoe advice video"},
            "audio": {"music_presence": "present"},
        },
        "inferred": {
            "hook": {"evidence": "bold text at 0.4s", "mechanism": "negation hook"},
            "narrative_structure": "problem -> tip",
            "audience_hypothesis": "beginner runners",
        },
        "generation": {"global_instructions": "Vertical, fast cuts"},
        "uncertainties": ["music track identity unknown"],
    }


class TestConfig:
    def test_model_id_from_env(self):
        cfg = load_baseline_config(env={"BASELINE_MODEL_ID": "gemini-2.0-flash"})
        assert cfg.model_id == "gemini-2.0-flash"

    def test_missing_model_id_fails_loudly(self):
        with pytest.raises(BaselineConfigError):
            load_baseline_config(env={})

    def test_config_file_precedence(self, tmp_path):
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps({"model_id": "m-from-file", "temperature": 0.7}))
        cfg = load_baseline_config(config_path=p, env={"BASELINE_MODEL_ID": "m-from-env"})
        assert cfg.model_id == "m-from-file"
        assert cfg.temperature == 0.7

    def test_api_key_required_and_never_serialized(self):
        cfg = load_baseline_config(env={"BASELINE_MODEL_ID": "x"})
        with pytest.raises(BaselineConfigError):
            cfg.require_api_key()
        d = cfg.to_dict()
        assert all("key" not in k for k in d)

    def test_cost_calculation(self):
        from tiktok_analytics_factory.baseline.config import PricingConfig

        pricing = PricingConfig(input_per_mtok_usd=1.0, output_per_mtok_usd=2.0)
        assert pricing.cost_usd(1_000_000, 500_000) == 2.0
        assert PricingConfig().cost_usd(10, 10) is None


class TestRequestConstruction:
    def test_prompt_contains_metadata_schema_and_instructions(self):
        template = PROMPT_PATH.read_text()
        rendered = render_prompt(template, {"video_id": "v1"}, {"type": "object"})
        assert '"video_id": "v1"' in rendered
        assert "{source_metadata}" not in rendered
        assert "{schema_json}" not in rendered

    def test_build_request_single_video_plus_prompt(self, tmp_path):
        config = make_config(tmp_path)
        prompt, parts = build_request_contents(
            config, b"fakevideo", "video/mp4", {"video_id": "v1"}
        )
        assert len(parts) == 2
        assert parts[0] == {"mime_type": "video/mp4", "data": b"fakevideo"}
        assert parts[1] == prompt
        # No ffprobe/whisper facts in the request path.
        assert "ffprobe" not in prompt

    def test_generation_settings_explicit(self, tmp_path):
        config = make_config(tmp_path)
        settings = build_generation_settings(config)
        assert settings["temperature"] == 0.3
        assert settings["response_mime_type"] == "application/json"

    def test_missing_prompt_fails(self, tmp_path):
        config = make_config(tmp_path)
        config.prompt_path = tmp_path / "nope.txt"
        with pytest.raises(RequestBuildError):
            build_request_contents(config, b"x", "video/mp4", {})


class TestParsingAndValidation:
    def test_parse_plain_json(self):
        out = parse_model_output('{"a": 1}')
        assert out == {"a": 1}

    def test_parse_fenced_json(self):
        out = parse_model_output('```json\n{"a": 1}\n```')
        assert out == {"a": 1}

    def test_malformed_is_failure_not_repaired(self):
        with pytest.raises(ParseError):
            parse_model_output('{"a": 1,,}')

    def test_non_object_rejected(self):
        with pytest.raises(ParseError):
            parse_model_output("[1, 2]")

    def test_valid_ir_against_committed_schema(self):
        result = validate_against_schema(valid_ir(), SCHEMA_PATH)
        assert result["valid"], result["errors"]

    def test_invalid_ir_reports_errors(self):
        bad = valid_ir()
        del bad["observed"]
        result = validate_against_schema(bad, SCHEMA_PATH)
        assert not result["valid"]
        assert any("observed" in e["message"] or "observed" in e["path"] for e in result["errors"])

    def test_extra_property_rejected(self):
        bad = valid_ir()
        bad["surprise"] = True
        result = validate_against_schema(bad, SCHEMA_PATH)
        assert not result["valid"]


class TestArtifactPersistence:
    def test_run_directory_layout(self, tmp_path):
        config = make_config(tmp_path)
        run_id = new_run_id()
        d = run_directory(config, "vid1", run_id)
        assert "decompilation" in str(d) and "single_pass" in str(d) and run_id in str(d)

    def test_all_artifacts_written(self, tmp_path):
        config = make_config(tmp_path)
        arts = RunArtifacts(run_directory(config, "vid1", "runX"))
        arts.write_prompt("PROMPT")
        arts.write_request(config, "vid1", sha256_bytes(b"v"), {}, {}, "2026-01-01T00:00:00Z")
        arts.write_raw_response("RAW")
        arts.write_parsed_response({"ok": True})
        arts.write_validation({"valid": True, "errors": []})
        usage_path = arts.write_usage(
            config,
            {"input_tokens": 1000, "output_tokens": 500},
            12.5,
            "2026-01-01T00:00:05Z",
        )
        expected = {
            "prompt.txt",
            "request.json",
            "response.raw.txt",
            "response.parsed.json",
            "validation.json",
            "usage.json",
        }
        assert expected <= {p.name for p in arts.directory.iterdir()}

        request = json.loads((arts.directory / "request.json").read_text())
        assert request["model_id"] == "gemini-test-model"
        assert request["prompt_version"] == config.prompt_version
        assert request["single_call"] is True
        assert len(request["video_sha256"]) == 64

        usage = json.loads(usage_path.read_text())
        assert usage["latency_seconds"] == 12.5
        assert usage["usage"]["input_tokens"] == 1000


class TestRunBaseline:
    def test_exactly_one_call_with_fake_caller(self, tmp_path):
        from tiktok_analytics_factory.baseline.run import run_baseline

        config = make_config(tmp_path)
        video = tmp_path / "video.mp4"
        video.write_bytes(b"videobytes")
        calls = []

        def fake_caller(parts, settings):
            calls.append((parts, settings))
            return json.dumps(valid_ir()), {"input_tokens": 10, "output_tokens": 5}

        result = run_baseline(
            config, video, "vid1", {"video_id": "vid1"}, run_id="r1", caller=fake_caller
        )
        assert len(calls) == 1  # exactly one primary call
        assert result["validation"]["valid"]
        assert result["parsed"]["schema_version"] == "0.1"
        for name in [
            "prompt.txt",
            "request.json",
            "response.raw.txt",
            "response.parsed.json",
            "validation.json",
            "usage.json",
        ]:
            assert (Path(result["directory"]) / name).exists()

    def test_malformed_output_recorded_as_failure(self, tmp_path):
        from tiktok_analytics_factory.baseline.run import run_baseline

        config = make_config(tmp_path)
        video = tmp_path / "video.mp4"
        video.write_bytes(b"x")

        result = run_baseline(
            config,
            video,
            "vid1",
            {},
            run_id="r2",
            caller=lambda parts, settings: ("not json {", {}),
        )
        assert not result["validation"]["valid"]
        assert "parse failure" in result["validation"]["errors"][0]["message"]

    def test_missing_video_fails_loudly(self, tmp_path):
        from tiktok_analytics_factory.baseline.run import run_baseline

        config = make_config(tmp_path)
        with pytest.raises(Exception):
            run_baseline(config, tmp_path / "missing.mp4", "vid1", {})
