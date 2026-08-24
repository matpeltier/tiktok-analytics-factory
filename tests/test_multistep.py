"""Tests for the two-pass multi-step decompiler (CI-safe: fakes, no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tiktok_analytics_factory.baseline.parsing import ParseError, parse_model_output
from tiktok_analytics_factory.contracts import project_creative_to_canonical, validate
from tiktok_analytics_factory.multistep.artifacts import MultiStepArtifacts
from tiktok_analytics_factory.multistep.config import (
    MultiStepConfig,
    MultiStepConfigError,
    load_multistep_config,
)
from tiktok_analytics_factory.multistep.evaluation import (
    build_comparison,
    build_evaluation_scaffold,
    evaluate_decision,
    record_manual_scores,
)
from tiktok_analytics_factory.multistep.merge import (
    MergeError,
    check_no_boundary_overwrite,
    merge_creative_ir,
)
from tiktok_analytics_factory.multistep.parsing import (
    ShotAnalysisError,
    validate_shot_analysis,
    validate_synthesis,
)
from tiktok_analytics_factory.multistep.request import (
    RequestBuildError,
    build_generation_settings,
    build_pass_a_request,
    build_pass_b_request,
    build_shot_list,
)
from tiktok_analytics_factory.multistep.runner import MultiStepRunError, run_multistep

VIDEO_ID = "6718335390845095173"

SHOTS_JSON = {
    "detector": "PySceneDetect.ContentDetector",
    "detector_version": "0.7.1",
    "parameters": {},
    "shots": [
        {"shot_id": "shot_001", "start_seconds": 0.0, "end_seconds": 0.5, "start_frame": 0, "end_frame": 15},
        {"shot_id": "shot_002", "start_seconds": 0.5, "end_seconds": 1.2, "start_frame": 15, "end_frame": 36},
    ],
}
MEDIA_FACTS = {
    "duration_seconds": 10.495011,
    "width": 720,
    "height": 1280,
    "fps": 30.0,
    "video_codec": "hevc",
    "sha256": "a" * 64,
}


def pass_a_payload() -> dict:
    return {
        "shots": [
            {
                "shot_id": "shot_001",
                "subjects": ["dog"],
                "actions": ["standing on boat seat"],
                "visual_description": "Fluffy dog on a boat seat facing the camera.",
                "framing": "medium",
                "camera_movement": "static",
                "on_screen_text": [],
                "spoken_dialogue": [],
                "audio": {"music": "upbeat music audible", "music_certainty": "observed",
                          "sfx": None, "sfx_certainty": "unknown"},
                "transition_in": "none_single_shot",
            },
            {
                "shot_id": "shot_002",
                "subjects": ["dog"],
                "actions": ["walking by a pool"],
                "visual_description": "Dog with pink collar walking along a poolside.",
                "framing": "wide",
                "camera_movement": "tracking",
                "on_screen_text": [{"text": "CHILLY PAD", "exact": True}],
                "spoken_dialogue": [],
                "audio": {"music_certainty": "observed"},
                "transition_in": "cut",
            },
        ],
        "uncertainties": ["music track identity unknown"],
    }


def synthesis_payload() -> dict:
    return {
        "observed_summary": "A fast-paced pet montage following a dog through summer activities.",
        "hook": {
            "description": "A fluffy dog stares into the camera panting on a boat.",
            "start_seconds": 0.0,
            "end_seconds": 1.0,
            "evidence": ["shot_001 [0-0.5s]: dog faces camera mouth open"],
        },
        "narrative_evidence": "Activity montage: boat, pool, towel, swim, wake.",
        "marketing_evidence": None,
        "first_product_appearance_seconds": None,
        "inferred": {
            "concept": {"value": "Summer pet adventure montage", "confidence": "high",
                        "rationale": "Water activities across all shots."},
            "target_audience_hypothesis": {"value": "Pet lovers on TikTok", "confidence": "medium",
                                           "rationale": "Cute-animal content and pet hashtags."},
            "hook_type": {"value": "direct_address", "confidence": "medium", "rationale": "Dog addresses camera."},
            "hook_mechanism": {"label": "cute animal engagement", "confidence": "high", "rationale": "Opening close-up."},
            "narrative_structure": {"value": "single_beat_no_narrative", "confidence": "high",
                                    "rationale": "Loose montage without story arc."},
            "attention_mechanisms": [
                {"label": "rapid cuts", "confidence": "high", "rationale": "10 shots in ~10s."},
            ],
            "persuasion_mechanisms": [
                {"label": "comment bait caption", "confidence": "high",
                 "rationale": "Caption asks viewers to comment their pet's name."},
            ],
            "commercial": {
                "status": "uncertain",
                "details": {
                    "product_presence": None,
                    "cta": {"text": None, "text_exact": None, "type": "comment"},
                },
            },
        },
        "generation": {
            "global_brief": "Vertical 9:16 summer pet montage, ~10s, lively music, quick hard cuts.",
            "timeline_pacing": "Roughly one shot per second.",
            "text_treatment": None,
            "transitions": "Hard cuts; keep energy high.",
            "continuity_constraints": ["Same dog across all shots."],
            "payoff_timing": None,
            "shots": [
                {
                    "shot_id": "shot_001",
                    "reconstruction_intent": "Open on a fluffy dog facing camera on a boat seat, medium close-up, ~0.5s.",
                },
                {
                    "shot_id": "shot_002",
                    "reconstruction_intent": "Track the dog walking along the poolside, low-angle handheld, ~0.6s.",
                },
            ],
        },
    }


def make_config(tmp_path: Path) -> MultiStepConfig:
    return MultiStepConfig(
        provider="google",
        model_id="gemini-test-a",
        synthesis_model_id="gemini-test-b",
        derived_root=tmp_path / "derived",
    )


def perception_dir(tmp_path: Path, with_frames: bool = False) -> Path:
    pdir = tmp_path / "derived" / VIDEO_ID / "perception" / "v1"
    pdir.mkdir(parents=True)
    (pdir / "media_facts.json").write_text(json.dumps(MEDIA_FACTS))
    (pdir / "shots.json").write_text(json.dumps(SHOTS_JSON))
    manifest: dict = {"frames": []}
    if with_frames:
        frames = []
        for shot in SHOTS_JSON["shots"]:
            frame_dir = pdir / "frames"
            frame_dir.mkdir(exist_ok=True)
            f = frame_dir / f"{shot['shot_id']}.jpg"
            f.write_bytes(b"\xff\xd8fakejpg")
            frames.append({"shot_id": shot["shot_id"], "path": str(f),
                           "timestamp_seconds": shot["start_seconds"],
                           "frame_index": shot["start_frame"]})
        manifest["frames"] = frames
    (pdir / "perception_manifest.json").write_text(json.dumps(manifest))
    return pdir


def source_metadata() -> dict:
    return {
        "video_id": VIDEO_ID,
        "raw": {
            "id": VIDEO_ID,
            "uploader": "scout2015",
            "description": "Scramble up ur name & I'll try to guess it #petsoftiktok",
            "webpage_url": f"https://www.tiktok.com/@scout2015/video/{VIDEO_ID}",
            "timestamp": 1564234358,
            "track": "original sound",
        },
    }


# --- config -----------------------------------------------------------------


def test_config_from_env():
    cfg = load_multistep_config(env={"MULTISTEP_MODEL_ID": "gemini-x"})
    assert cfg.model_id == "gemini-x"
    assert cfg.synthesis_model == "gemini-x"


def test_config_missing_model_fails_loudly():
    with pytest.raises(MultiStepConfigError):
        load_multistep_config(env={})


# --- request construction from deterministic shot data -----------------------


class TestRequests:
    def test_shot_list_copies_deterministic_timestamps(self):
        shot_list = build_shot_list(SHOTS_JSON)
        assert [s["start_seconds"] for s in shot_list] == [0.0, 0.5]
        assert [s["end_seconds"] for s in shot_list] == [0.5, 1.2]

    def test_pass_a_request_contains_frames_and_prompt(self, tmp_path):
        pdir = perception_dir(tmp_path, with_frames=True)
        config = make_config(tmp_path)
        manifest = json.loads((pdir / "perception_manifest.json").read_text())
        video_bytes = b"fakevideo"
        prompt, parts = build_pass_a_request(config, video_bytes, build_shot_list(SHOTS_JSON, manifest["frames"]))
        roles = [p.get("role") for p in parts]
        assert roles[0] == "source_video"
        assert roles[1] == "frame:shot_001" and roles[2] == "frame:shot_002"
        assert roles[-1] == "prompt"
        assert "shot_001" in prompt and "0.5" in prompt
        # prohibitions are present verbatim in the versioned prompt
        assert "Do NOT change, restate, or re-estimate shot start/end timestamps" in prompt

    def test_pass_a_request_fails_loudly_on_missing_frame(self, tmp_path):
        config = make_config(tmp_path)
        shot_list = [{"shot_id": "shot_001", "start_seconds": 0.0, "end_seconds": 0.5,
                      "representative_frame": {"path": str(tmp_path / "nope.jpg")}}]
        with pytest.raises(RequestBuildError):
            build_pass_a_request(config, b"v", shot_list)

    def test_pass_b_prompt_embeds_all_inputs(self, tmp_path):
        config = make_config(tmp_path)
        prompt, parts = build_pass_b_request(
            config, b"v", source_metadata(), MEDIA_FACTS,
            build_shot_list(SHOTS_JSON), pass_a_payload(),
        )
        for marker in ("original sound", "10.495011", "shot_002", "CHILLY PAD"):
            assert marker in prompt
        assert parts[-1]["role"] == "prompt"

    def test_generation_settings_json_mode(self, tmp_path):
        settings = build_generation_settings(make_config(tmp_path))
        assert settings["response_mime_type"] == "application/json"

    def test_pass_a_v0_3_prompt_anchors_single_shot_alignment(self, tmp_path):
        pdir = perception_dir(tmp_path, with_frames=True)
        config = make_config(tmp_path)
        manifest = json.loads((pdir / "perception_manifest.json").read_text())
        shot_list = build_shot_list(SHOTS_JSON, manifest["frames"])
        prompt, parts = build_pass_a_request(config, b"v", [shot_list[1]])
        roles = [p.get("role") for p in parts]
        assert roles == ["source_video", "frame:shot_002", "prompt"]
        assert "EXACTLY ONE shot" in prompt
        assert "TRUST THE FRAME" in prompt
        assert "shot_001" not in prompt

    def test_config_pass_a_batch_size_from_env(self):
        cfg = load_multistep_config(env={
            "MULTISTEP_MODEL_ID": "gemini-x",
            "MULTISTEP_PASS_A_BATCH_SIZE": "5",
        })
        assert cfg.pass_a_batch_size == 5

    def test_per_batch_wrong_shot_id_fails_run(self, tmp_path):
        perception_dir(tmp_path)
        config = make_config(tmp_path)
        video = tmp_path / "video.mp4"
        video.write_bytes(b"f")
        payload = pass_a_payload()

        def call_a(parts, settings):
            # batch 0 (shot_001) answered with shot_002's analysis
            return json.dumps({"shots": [payload["shots"][1]]}), {}

        with pytest.raises(MultiStepRunError, match="batch 0"):
            run_multistep(config, video, VIDEO_ID, source_metadata(), caller=call_a)


# --- parsing -----------------------------------------------------------------


class TestParsing:
    def test_parse_plain_and_fenced_json(self):
        obj = {"shots": []}
        assert parse_model_output(json.dumps(obj)) == obj
        assert parse_model_output(f"```json\n{json.dumps(obj)}\n```") == obj

    def test_parse_invalid_raises(self):
        with pytest.raises(ParseError):
            parse_model_output("not json at all")

    def test_validate_shot_analysis_missing_shot_fails(self):
        payload = pass_a_payload()
        payload["shots"] = payload["shots"][:1]
        with pytest.raises(ShotAnalysisError):
            validate_shot_analysis(payload, ["shot_001", "shot_002"])

    def test_validate_shot_analysis_duplicate_fails(self):
        payload = pass_a_payload()
        payload["shots"].append(payload["shots"][0])
        with pytest.raises(ShotAnalysisError):
            validate_shot_analysis(payload, ["shot_001", "shot_002"])

    def test_validate_synthesis_requires_sections(self):
        with pytest.raises(ShotAnalysisError):
            validate_synthesis({"observed_summary": "x"})


# --- deterministic timestamp protection + provenance merge -------------------


class TestMerge:
    def decompilation_block(self) -> dict:
        return {
            "schema_version": "0.1",
            "pipeline_version": "multistep_v1",
            "model_id": "a (pass A) + b (pass B)",
            "provider": "google",
            "prompt_version": "pa (pass A) + pb (pass B)",
            "created_at": "2026-08-23T00:00:00+00:00",
            "annotation_mode": "automated",
        }

    def merged(self, pass_a=None, synthesis=None) -> dict:
        ir = merge_creative_ir(
            source_metadata=source_metadata(),
            media_facts=MEDIA_FACTS,
            shots_result=SHOTS_JSON,
            shot_analyses_parsed=pass_a or pass_a_payload(),
            synthesis_parsed=synthesis or synthesis_payload(),
            decompilation=self.decompilation_block(),
        )
        validate(ir, "creative_ir_v0_1")
        return ir

    def test_merged_ir_validates_against_committed_schema(self):
        ir = self.merged()
        assert ir["schema"] == {"name": "creative_ir", "version": "0.1"}
        assert len(ir["observed"]["shots"]) == 2

    def test_model_cannot_overwrite_deterministic_timestamps(self):
        tampered = pass_a_payload()
        tampered["shots"][0]["start_seconds"] = 99.0
        tampered["shots"][0]["end_seconds"] = 100.0
        with pytest.raises(MergeError):
            check_no_boundary_overwrite(tampered["shots"][0], SHOTS_JSON["shots"][0])
        # a tampered Pass A payload can never reach the merged IR
        with pytest.raises(MergeError):
            self.merged(pass_a=tampered)

    def test_provenance_merge_distinguishes_deterministic_vs_model(self):
        ir = self.merged()
        shot = ir["observed"]["shots"][1]
        kinds = {e["kind"] for e in shot["evidence"]}
        assert kinds == {"deterministic", "model_observation"}
        det_refs = [e for e in shot["evidence"] if e["kind"] == "deterministic"]
        assert str(SHOTS_JSON["shots"][1]["start_seconds"]) in det_refs[0]["reference"]
        # deterministic facts come from ffprobe, not from the model payloads
        assert ir["source"]["duration_seconds"] == MEDIA_FACTS["duration_seconds"]
        assert ir["source"]["artifact_sha256"] == MEDIA_FACTS["sha256"]

    def test_uncertain_dialogue_not_marked_exact(self):
        payload = pass_a_payload()
        payload["shots"][1]["spoken_dialogue"] = [
            {"speaker": None, "text": "sounds like 'good boy'", "exact": True, "confidence": "low"}
        ]
        ir = self.merged(pass_a=payload)
        spoken = ir["observed"]["shots"][1]["spoken_dialogue"][0]
        assert spoken["exact"] is False

    def test_unknown_generation_shot_id_fails(self):
        bad = synthesis_payload()
        bad["generation"]["shots"].append({"shot_id": "shot_999", "reconstruction_intent": "?"})
        with pytest.raises(MergeError):
            self.merged(synthesis=bad)

    def test_non_commercial_with_cta_evidence_fails_loudly(self):
        """Regression: run 20260823T083309Z merged a self-contradictory
        synthesis (non_commercial status + comment-bait persuasion)."""
        bad = synthesis_payload()
        bad["inferred"]["commercial"] = {"status": "non_commercial", "details": None}
        with pytest.raises(MergeError, match="call to action"):
            self.merged(synthesis=bad)

    def test_non_commercial_without_cta_evidence_is_accepted(self):
        ok = synthesis_payload()
        ok["inferred"]["persuasion_mechanisms"] = [
            {"label": "cuteness appeal", "confidence": "high", "rationale": "Cute dog."}
        ]
        ok["marketing_evidence"] = None
        ok["inferred"]["commercial"] = {"status": "non_commercial", "details": None}
        ir = self.merged(synthesis=ok)
        assert ir["inferred"]["commercial"]["status"] == "non_commercial"

    def test_vague_reconstruction_intent_fails(self):
        bad = synthesis_payload()
        bad["generation"]["shots"][0]["reconstruction_intent"] = "dog on boat."
        with pytest.raises(MergeError, match="vague"):
            self.merged(synthesis=bad)

    def test_missing_generation_shot_coverage_fails(self):
        bad = synthesis_payload()
        bad["generation"]["shots"] = bad["generation"]["shots"][:1]
        with pytest.raises(MergeError, match="missing reconstruction"):
            self.merged(synthesis=bad)


    def test_canonical_projection_succeeds_on_merged_ir(self):
        canonical = project_creative_to_canonical(self.merged())
        validate(canonical, "canonical_ir_v0_1")
        assert canonical["features"]["shot_count"] == 2
        assert canonical["features"]["visible_text_present"] is True


# --- runner (fakes), persistence, usage aggregation --------------------------

class TestThrottling:
    def test_wait_for_model_gap_enforces_spacing(self, monkeypatch):
        from tiktok_analytics_factory.multistep import runner as runner_module

        monkeypatch.setattr(runner_module, "_last_model_call_monotonic", None)
        sleeps = []
        fake_clock = {"t": 100.0}
        monkeypatch.setattr(runner_module.time, "monotonic", lambda: fake_clock["t"])

        def fake_sleep(seconds):
            sleeps.append(seconds)
            fake_clock["t"] += seconds

        monkeypatch.setattr(runner_module.time, "sleep", fake_sleep)

        # First call records the timestamp without sleeping.
        runner_module._wait_for_model_gap(30.0)
        assert sleeps == []

        # Second call 5s later must sleep the remaining 25s.
        fake_clock["t"] += 5.0
        runner_module._wait_for_model_gap(30.0)
        assert len(sleeps) == 1 and abs(sleeps[0] - 25.0) < 1e-6

        # Non-positive gap disables throttling.
        runner_module._wait_for_model_gap(0.0)
        assert len(sleeps) == 1
        monkeypatch.setattr(runner_module, "_last_model_call_monotonic", None)


class TestRunner:
    def fake_callers(self, raw_a=None, raw_b=None, usage=(111, 222)):
        raw_a = raw_a if raw_a is not None else json.dumps(pass_a_payload())
        raw_b = raw_b if raw_b is not None else json.dumps(synthesis_payload())
        calls = {"count": 0}

        def call_a(parts, settings):
            calls["count"] += 1
            # v0.3: one shot per request; answer only for the requested ids
            prompt = next(p for p in parts if p.get("role") == "prompt")["data"].decode()
            ids = [sid for sid in ("shot_001", "shot_002") if sid in prompt]
            try:
                parsed_raw = json.loads(raw_a)
            except json.JSONDecodeError:
                parsed_raw = None
            if isinstance(parsed_raw, dict) and "shots" in parsed_raw:
                payload = {"shots": [s for s in parsed_raw["shots"] if s["shot_id"] in ids],
                           "uncertainties": ["music track identity unknown"]}
                raw = json.dumps(payload)
            else:
                raw = raw_a
            return raw, {"input_tokens": usage[0], "output_tokens": usage[1], "total_tokens": usage[0] + usage[1]}

        def call_b(parts, settings):
            calls["count"] += 1
            return raw_b, {"input_tokens": usage[0], "output_tokens": usage[1], "total_tokens": usage[0] + usage[1]}

        return call_a, call_b, calls

    def test_full_run_persists_all_artifacts(self, tmp_path):
        perception_dir(tmp_path)
        config = make_config(tmp_path)
        config.pricing.input_per_mtok_usd = 1.0
        config.pricing.output_per_mtok_usd = 2.0
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fakevideo")
        call_a, call_b, calls = self.fake_callers()

        result = run_multistep(
            config, video, VIDEO_ID, source_metadata(),
            run_id="run-test", caller=call_a, synthesis_caller=call_b,
        )
        directory = Path(result["directory"])
        assert directory == config.decompilation_dir(VIDEO_ID, "run-test")
        expected = [
            "media_facts.json", "shots.json",
            "shot_analysis/request_000.json", "shot_analysis/response_000.raw.txt",
            "shot_analysis/response_000.parsed.json",
            "shot_analysis/request_001.json", "shot_analysis/response_001.raw.txt",
            "shot_analysis/response_001.parsed.json",
            "synthesis/prompt.txt", "synthesis/response.raw.txt",
            "synthesis/response.parsed.json",
            "creative_ir.json", "canonical_ir.json", "validation.json", "usage.json",
            "evaluation.json",
        ]
        for rel in expected:
            assert (directory / rel).exists(), f"missing artifact {rel}"
        evaluation = json.loads((directory / "evaluation.json").read_text())
        assert evaluation["schema_validation_success"] is True
        assert all(evaluation["deterministic_fact_checks"].values())
        # v0.3 default: one Pass A request per shot + one Pass B request
        assert evaluation["model_call_count"] == 3
        assert evaluation["cost_usd"] is not None
        assert evaluation["scores_pending_manual_review"] is True
        # certain claims from the fixture payload are inventoried for review
        kinds = {c["kind"] for c in evaluation["certain_claim_inventory"]}
        assert "exact_on_screen_text" in kinds
        validation = json.loads((directory / "validation.json").read_text())
        assert validation == {
            "valid": True, "stage": "complete",
            "creative_ir_schema": "pass", "canonical_projection": "pass",
        }
        creative_ir = json.loads((directory / "creative_ir.json").read_text())
        canonical_ir = json.loads((directory / "canonical_ir.json").read_text())
        assert creative_ir["decompilation"]["pipeline_version"] == "multistep_v1"
        assert "(pass A)" in creative_ir["decompilation"]["model_id"]
        assert "(pass B)" in creative_ir["decompilation"]["model_id"]
        assert canonical_ir["schema"]["name"] == "canonical_ir"

    def test_usage_aggregation_by_pass(self, tmp_path):
        perception_dir(tmp_path)
        config = make_config(tmp_path)
        pricing_input, pricing_output = 1.5, 7.5
        config.pricing.input_per_mtok_usd = pricing_input
        config.pricing.output_per_mtok_usd = pricing_output
        video = tmp_path / "video.mp4"
        video.write_bytes(b"f")
        call_a, call_b, _ = self.fake_callers()

        result = run_multistep(config, video, VIDEO_ID, source_metadata(), caller=call_a, synthesis_caller=call_b)
        usage = result["usage"]
        # 2 Pass A batches (one per shot) + 1 Pass B
        assert usage["model_call_count"] == 3
        assert [p["shot_ids"] for p in usage["passes"][:2]] == [["shot_001"], ["shot_002"]]
        assert usage["total_usage"]["input_tokens"] == 333
        assert usage["total_usage"]["output_tokens"] == 666
        expected_cost = round((111 / 1e6 * pricing_input + 222 / 1e6 * pricing_output), 6)
        assert usage["passes"][0]["cost_usd"] == expected_cost
        assert usage["total_cost_usd"] == round(expected_cost * 3, 6)

    def test_invalid_pass_a_json_fails_run_but_keeps_raw(self, tmp_path):
        perception_dir(tmp_path)
        config = make_config(tmp_path)
        video = tmp_path / "video.mp4"
        video.write_bytes(b"f")
        call_a, _, _ = self.fake_callers(raw_a="definitely not json")
        with pytest.raises(MultiStepRunError, match="Pass A parse failure"):
            run_multistep(config, video, VIDEO_ID, source_metadata(), caller=call_a)
        runs = sorted((config.derived_root / VIDEO_ID / "decompilation" / "multi_step").iterdir())
        raw = (runs[-1] / "shot_analysis" / "response_000.raw.txt").read_text()
        assert raw == "definitely not json"

    def test_schema_validation_failure_path_blocks_success_artifacts(self, tmp_path):
        perception_dir(tmp_path)
        config = make_config(tmp_path)
        video = tmp_path / "video.mp4"
        video.write_bytes(b"f")
        bad_synthesis = synthesis_payload()
        bad_synthesis["generation"]["global_brief"] = ""  # minLength 1 violated post-merge fallback? summary still non-empty
        bad_synthesis["commercial_bad"] = True
        # force schema failure via invalid commercial status path
        bad_synthesis["inferred"]["commercial"] = {"status": "non_commercial", "details": {"product_presence": "x"}}
        call_a, call_b, _ = self.fake_callers(raw_b=json.dumps(bad_synthesis))
        from tiktok_analytics_factory.multistep.merge import _commercial
        # direct unit-level check of the failure mode instead of relying on coercion
        assert _commercial({"status": "non_commercial", "details": {"product_presence": "x"}}) == {
            "status": "non_commercial", "details": None,
        }
        # end-to-end: merge coerces, but a genuinely broken IR must fail loudly
        from tiktok_analytics_factory.multistep.merge import merge_creative_ir as mci
        from tiktok_analytics_factory.multistep.parsing import validate_creative_ir
        broken = mci(
            source_metadata=source_metadata(), media_facts=MEDIA_FACTS,
            shots_result=SHOTS_JSON, shot_analyses_parsed=pass_a_payload(),
            synthesis_parsed=synthesis_payload(),
            decompilation={"schema_version": "9.9", "pipeline_version": "x", "model_id": "m",
                           "provider": "p", "prompt_version": "pv", "created_at": "2026-08-23T00:00:00+00:00",
                           "annotation_mode": "automated"},
        )
        with pytest.raises(ParseError):
            validate_creative_ir(broken)


# --- evaluation scaffold -------------------------------------------------------


def _merged_creative_ir() -> dict:
    return merge_creative_ir(
        source_metadata=source_metadata(),
        media_facts=MEDIA_FACTS,
        shots_result=SHOTS_JSON,
        shot_analyses_parsed=pass_a_payload(),
        synthesis_parsed=synthesis_payload(),
        decompilation={
            "schema_version": "0.1", "pipeline_version": "multistep_v1",
            "model_id": "gemini-test-a (pass A) + gemini-test-b (pass B)",
            "provider": "google", "prompt_version": "pa (pass A) + pb (pass B)",
            "created_at": "2026-08-23T00:00:00+00:00",
            "annotation_mode": "automated",
        },
    )


class TestEvaluationScaffold:
    def test_deterministic_checks_pass_on_valid_merge(self):
        usage = {"total_latency_seconds": 12.5, "total_usage": {"input_tokens": 10},
                 "total_cost_usd": 0.01, "model_call_count": 2}
        scaffold = build_evaluation_scaffold(_merged_creative_ir(), MEDIA_FACTS, SHOTS_JSON, usage)
        assert all(scaffold["deterministic_fact_checks"].values())
        assert scaffold["deterministic_fact_checks"]["duration_equal"] is True
        assert scaffold["deterministic_fact_checks"]["boundaries_equal"] is True
        assert scaffold["latency_seconds"] == 12.5
        assert scaffold["model_call_count"] == 2

    def test_boundary_mismatch_is_detected(self):
        ir = _merged_creative_ir()
        ir["observed"]["shots"][0]["end_seconds"] = 99.0
        scaffold = build_evaluation_scaffold(ir, MEDIA_FACTS, SHOTS_JSON, {})
        assert scaffold["deterministic_fact_checks"]["boundaries_equal"] is False

    def test_exact_quotes_and_observed_audio_are_inventoried(self):
        scaffold = build_evaluation_scaffold(_merged_creative_ir(), MEDIA_FACTS, SHOTS_JSON, {})
        kinds = {c["kind"] for c in scaffold["certain_claim_inventory"]}
        assert kinds == {"exact_on_screen_text", "observed_music_identity"}
        text_claim = next(c for c in scaffold["certain_claim_inventory"]
                          if c["kind"] == "exact_on_screen_text")
        assert text_claim["claim"] == "CHILLY PAD"
        assert text_claim["shot_id"] == "shot_002"


# --- comparison report + decision gate ---------------------------------------


def test_record_manual_scores_fills_scaffold():
    scaffold = build_evaluation_scaffold(_merged_creative_ir(), MEDIA_FACTS, SHOTS_JSON, {})
    cats = {name: {"score": 4, "notes": "n", "evidence": "e"} for name in
            ("media_facts", "shot_boundaries_timeline", "visible_text_ocr", "dialogue",
             "visual_description", "camera_editing", "audio", "hook", "narrative",
             "marketing_commercial_reasoning", "reconstruction_quality")}
    out = record_manual_scores(scaffold, cats, unsupported_claims=[{"claim": "x"}])
    assert out["scores_pending_manual_review"] is False
    assert out["categories"]["media_facts"]["score"] == 4
    assert out["unsupported_claims"] == [{"claim": "x"}]


def test_record_manual_scores_rejects_unknown_category():
    with pytest.raises(ValueError):
        record_manual_scores({}, {"not_a_category": {"score": 4, "notes": "n", "evidence": "e"}})


def base_evaluation(scores: dict[str, int], unsupported: int = 3) -> dict:
    return {
        "run_metadata": {"video_id": VIDEO_ID},
        "categories": {name: {"score": score} for name, score in scores.items()},
        "unsupported_claims": [{"claim": f"c{i}"} for i in range(unsupported)],
        "missed_important_facts": [{"fact": "f"}],
        "schema_validation_success": True,
        "latency_seconds": 27.6,
        "api_usage": {"input_tokens": 4313, "output_tokens": 1904, "total_tokens": 8671},
        "cost_usd": 0.02075,
    }


BASE_SCORES = {
    "media_facts": 4, "shot_boundaries_timeline": 4, "visible_text_ocr": 2,
    "dialogue": 5, "visual_description": 4, "camera_editing": 4, "audio": 4,
    "hook": 4, "narrative": 4, "marketing_commercial_reasoning": 3,
    "reconstruction_quality": 4,
}
MULTI_SCORES = {
    "media_facts": 5, "shot_boundaries_timeline": 5, "visible_text_ocr": 4,
    "dialogue": 5, "visual_description": 4, "camera_editing": 4, "audio": 4,
    "hook": 4, "narrative": 4, "marketing_commercial_reasoning": 4,
    "reconstruction_quality": 4,
}


def test_comparison_report_structure():
    baseline = base_evaluation(BASE_SCORES)
    multistep = base_evaluation(MULTI_SCORES, unsupported=1)
    comparison = build_comparison(baseline, multistep)
    assert len(comparison["categories"]) == 11
    ocr_row = next(r for r in comparison["categories"] if r["category"] == "visible_text_ocr")
    assert ocr_row["single_pass_score"] == 2 and ocr_row["multi_step_score"] == 4
    assert ocr_row["delta"] == 2
    assert comparison["overall_average"]["single_pass"] < comparison["overall_average"]["multi_step"]
    assert comparison["unsupported_claims"]["multi_step_count"] == 1
    assert comparison["operational"]["multi_step"]["model_calls"] == 2
    assert comparison["operational"]["single_pass"]["model_calls"] == 1


def test_decision_gate_validated_for_pilot():
    baseline = base_evaluation(BASE_SCORES)
    multistep = base_evaluation(MULTI_SCORES, unsupported=1)
    multistep["latency_seconds"] = 41.0
    multistep["cost_usd"] = 0.03
    comparison = build_comparison(baseline, multistep)
    comparison["canonical_projection_pass"] = True
    comparison["deterministic_fact_checks"] = {
        "duration_equal": True, "resolution_equal": True, "fps_equal": True,
        "codec_equal": True, "boundaries_equal": True,
    }
    result = evaluate_decision(comparison)
    assert result["decision"] == "validated-for-pilot"


def test_decision_gate_needs_one_video_fix():
    baseline = base_evaluation(BASE_SCORES)
    weak = dict(MULTI_SCORES)
    weak["visible_text_ocr"] = 2  # regression below baseline parity requirement
    weak["hook"] = 3  # hook below baseline
    multistep = base_evaluation(weak, unsupported=4)
    comparison = build_comparison(baseline, multistep)
    comparison["canonical_projection_pass"] = False
    comparison["deterministic_fact_checks"] = {"duration_equal": False}
    result = evaluate_decision(comparison)
    assert result["decision"] == "needs-one-video-fix"
    gates = {g["gate"]: g["passed"] for g in result["gate_results"]}
    assert not gates["canonical_ir_projection"]
    assert not gates["hook_at_least_baseline"]
    assert not gates["fewer_unsupported_claims_than_baseline"]
    assert result["follow_up"]
