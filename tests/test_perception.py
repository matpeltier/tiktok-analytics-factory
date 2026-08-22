"""Deterministic tests for the perception layer.

Requires ffmpeg/ffprobe and PySceneDetect locally; no network access.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("scenedetect")
if shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None:
    pytest.skip("ffmpeg/ffprobe not available", allow_module_level=True)

from tiktok_analytics_factory.perception import (
    PerceptionConfig,
    detect_shots,
    evaluate_boundaries,
    extract_representative_frames,
    probe_media,
    run_perception,
)
from tiktok_analytics_factory.perception.errors import (
    CorruptMediaError,
    NoVideoStreamError,
    VideoNotFoundError,
)
from tiktok_analytics_factory.perception.probe import parse_fps_rational, sha256_file

from tests.perception_video_fixtures import (
    make_corrupt_file,
    make_multicut_video,
    make_no_audio_video,
    make_solid_color_video,
)


@pytest.fixture
def solid_video(tmp_path: Path) -> Path:
    p = tmp_path / "solid.mp4"
    make_solid_color_video(p, duration=2.0, color="red", with_audio=True)
    return p


@pytest.fixture
def multicut_video(tmp_path: Path) -> tuple[Path, list[float]]:
    p = tmp_path / "multicut.mp4"
    cuts = make_multicut_video(p)
    return p, cuts


class TestProbeMedia:
    def test_basic_facts(self, solid_video: Path):
        facts = probe_media(solid_video)
        assert 1.9 <= facts.duration_seconds <= 2.2
        assert (facts.width, facts.height) == (64, 64)
        assert facts.aspect_ratio_label == "1:1"
        assert abs(facts.aspect_ratio_float - 1.0) < 1e-6
        assert facts.fps == pytest.approx(30.0)
        assert facts.video_codec in ("h264", "mpeg4", "vp9")
        assert facts.has_audio is True
        assert facts.audio_codec is not None
        assert len(facts.sha256) == 64
        assert facts.file_size_bytes > 0
        assert facts.container_format
        assert facts.ffprobe_version

    def test_sha_matches_independent_hash(self, solid_video: Path):
        assert probe_media(solid_video).sha256 == sha256_file(solid_video)

    def test_rational_fps_parsing(self):
        frac = parse_fps_rational("30000/1001")
        assert float(frac) == pytest.approx(29.97002997, rel=1e-6)

    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(VideoNotFoundError):
            probe_media(tmp_path / "nope.mp4")

    def test_corrupt_media(self, tmp_path: Path):
        p = tmp_path / "corrupt.mp4"
        make_corrupt_file(p)
        with pytest.raises(CorruptMediaError):
            probe_media(p)

    def test_no_video_stream(self, tmp_path: Path):
        audio = tmp_path / "audio.m4a"
        proc = _ffmpeg(
            ["-f", "lavfi", "-i", "sine=frequency=440:d=0.5", str(audio)]
        )
        assert proc == 0
        with pytest.raises(NoVideoStreamError):
            probe_media(audio)


def _ffmpeg(args: list[str]) -> int:
    import subprocess

    return subprocess.run(["ffmpeg", *args], capture_output=True).returncode


class TestNoAudioVideo:
    def test_absent_audio_is_a_fact_not_an_error(self, tmp_path: Path):
        p = tmp_path / "silent.mp4"
        make_no_audio_video(p)
        facts = probe_media(p)
        assert facts.has_audio is False
        assert facts.audio_codec is None


class TestDetectShots:
    def test_no_cut_yields_single_shot(self, solid_video: Path):
        result = detect_shots(solid_video)
        assert len(result.shots) == 1
        shot = result.shots[0]
        assert shot.shot_id == "shot_001"
        assert shot.start_seconds == 0.0
        assert shot.end_seconds == pytest.approx(result.duration_seconds, abs=1.5)

    def test_ordered_non_overlapping_and_full_coverage(self, multicut_video):
        video, gt_cuts = multicut_video
        result = detect_shots(video)
        shots = result.shots
        assert len(shots) >= len(gt_cuts)
        assert shots[0].start_seconds == 0.0
        for a, b in zip(shots, shots[1:]):
            assert b.start_seconds >= a.end_seconds - 1e-6
            assert a.end_seconds > a.start_seconds
        # ids stable and ordered
        assert [s.shot_id for s in shots] == [
            f"shot_{i + 1:03d}" for i in range(len(shots))
        ]
        # last shot ends at probed duration within tolerance
        facts = probe_media(video)
        assert shots[-1].end_seconds == pytest.approx(facts.duration_seconds, abs=1.0 / facts.fps * 3)

    def test_detector_provenance(self, solid_video: Path):
        cfg = PerceptionConfig(threshold=25.0)
        result = detect_shots(solid_video, cfg)
        assert result.detector == "ContentDetector"
        assert result.detector_version
        assert result.parameters["threshold"] == 25.0

    def test_deterministic_boundaries(self, multicut_video):
        video, _ = multicut_video
        r1 = detect_shots(video)
        r2 = detect_shots(video)
        assert [(s.start_seconds, s.end_seconds) for s in r1.shots] == [
            (s.start_seconds, s.end_seconds) for s in r2.shots
        ]


class TestRepresentativeFrames:
    def test_one_frame_per_shot_deterministic_names(self, multicut_video, tmp_path: Path):
        video, _ = multicut_video
        result = detect_shots(video)
        out1 = tmp_path / "frames1"
        artifacts1 = extract_representative_frames(video, result, out1)
        assert len(artifacts1) == len(result.shots)
        for art in artifacts1:
            assert Path(art.path).exists()
            assert Path(art.path).name == f"{art.shot_id}.jpg"
            mid = (result.shots[int(art.shot_id[-3:]) - 1].start_seconds +
                   result.shots[int(art.shot_id[-3:]) - 1].end_seconds) / 2
            assert art.timestamp_seconds == pytest.approx(mid)

        out2 = tmp_path / "frames2"
        artifacts2 = extract_representative_frames(video, result, out2)
        assert [a.timestamp_seconds for a in artifacts1] == [
            a.timestamp_seconds for a in artifacts2
        ]


class TestBoundaryEvaluation:
    def test_metrics(self):
        detected = [1.02, 2.01, 4.5]
        truth = [1.0, 2.05, 3.5]
        ev = evaluate_boundaries(detected, truth, tolerance_seconds=0.30)
        assert ev.true_positives == 2
        assert ev.false_positives == 1
        assert ev.missed == 1
        assert ev.precision == pytest.approx(2 / 3)
        assert ev.recall == pytest.approx(2 / 3)
        assert ev.f1 == pytest.approx(2 / 3)
        assert ev.median_absolute_error_seconds == pytest.approx(0.03)

    def test_empty_inputs(self):
        ev = evaluate_boundaries([], [])
        assert ev.precision == 0.0 and ev.recall == 0.0

    def test_synthetic_fixture_evaluation(self, multicut_video):
        video, gt_cuts = multicut_video
        result = detect_shots(video)
        detected = [s.start_seconds for s in result.shots if s.start_seconds > 0]
        ev = evaluate_boundaries(detected, gt_cuts, tolerance_seconds=0.30)
        assert ev.true_positives == len(gt_cuts)
        assert ev.false_positives == 0
        assert ev.recall == 1.0
        assert ev.median_absolute_error_seconds <= 0.30


class TestRunPerception:
    def test_end_to_end_artifacts(self, multicut_video, tmp_path: Path):
        video, _ = multicut_video
        out = tmp_path / "out" / "vid" / "perception" / "v1"
        manifest = run_perception(video, out)
        assert (out / "media_facts.json").exists()
        assert (out / "shots.json").exists()
        assert (out / "manifest.json").exists()

        facts = json.loads((out / "media_facts.json").read_text())
        shots_doc = json.loads((out / "shots.json").read_text())
        assert facts["sha256"] == manifest.video_sha256
        assert shots_doc["detector"] == "ContentDetector"
        frame_paths = [Path(a.path) for a in manifest.frames]
        assert all(p.exists() for p in frame_paths)
        assert {p.parent.name for p in frame_paths} == {"frames"}

    def test_manifest_serializable(self, solid_video: Path, tmp_path: Path):
        manifest = run_perception(solid_video, tmp_path / "o")
        doc = manifest.to_dict()
        json.dumps(doc)  # must be plain JSON types
        assert doc["pipeline_version"] == "v1"
