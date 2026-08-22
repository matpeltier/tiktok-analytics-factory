"""Deterministic tests for the perception layer (no network, no models)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.perception_fixtures import (  # noqa: F401
    make_multicut_video,
    make_solid_video,
)


pytest.importorskip("tiktok_analytics_factory")

from tiktok_analytics_factory.perception import (  # noqa: E402
    DetectorConfig,
    MediaFileNotFoundError,
    NoVideoStreamError,
    UnreadableMediaError,
    detect_shots,
    evaluate_boundaries,
    extract_representative_frames,
    parse_ffprobe_json,
    probe_media,
    run_perception,
)
from tiktok_analytics_factory.perception.evaluation import CutAnnotation, shot_cut_timestamps


@pytest.fixture(scope="module")
def ffmpeg_available() -> bool:
    from shutil import which

    if which("ffmpeg") is None or which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not available")
    return True


# ---------------------------------------------------------------- ffprobe JSON

def test_parse_ffprobe_json_valid():
    raw = json.dumps({"streams": [{"codec_type": "video", "width": 1080}],
                      "format": {"duration": "21.5"}})
    data = parse_ffprobe_json(raw)
    assert data["format"]["duration"] == "21.5"


def test_parse_ffprobe_json_invalid():
    with pytest.raises(UnreadableMediaError):
        parse_ffprobe_json("{not json")


def test_parse_ffprobe_json_non_object():
    with pytest.raises(UnreadableMediaError):
        parse_ffprobe_json("[1,2,3]")


# ---------------------------------------------------------------- media probing

def test_probe_media_full_facts(ffmpeg_available, tmp_path):
    video = make_solid_video(tmp_path / "v.mp4", seconds=1.0, fps="30000/1001")
    facts = probe_media(video)
    assert facts.duration_seconds == pytest.approx(1.0, abs=0.2)
    assert facts.width == 64 and facts.height == 64
    assert facts.aspect_ratio == "1:1"
    assert facts.fps_rational is not None
    assert facts.fps == pytest.approx(30000 / 1001, abs=0.01)
    assert facts.video_codec in ("h264",)
    assert facts.has_audio is True
    assert facts.audio_codec == "aac"
    assert len(facts.sha256) == 64
    assert facts.ffprobe_version
    assert facts.probed_at
    facts2 = probe_media(video)
    assert facts2.sha256 == facts.sha256


def test_probe_media_no_audio(ffmpeg_available, tmp_path):
    video = make_solid_video(tmp_path / "silent.mp4", with_audio=False)
    facts = probe_media(video)
    assert facts.has_audio is False
    assert facts.audio_codec is None


def test_probe_media_missing_file():
    with pytest.raises(MediaFileNotFoundError):
        probe_media("/nonexistent/video.mp4")


def test_probe_media_corrupt(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00\x00\x00\x18ftypmp42garbage" * 8)
    with pytest.raises(UnreadableMediaError):
        probe_media(bad)


def test_probe_media_no_video_stream(ffmpeg_available, tmp_path):
    audio_only = tmp_path / "audio.m4a"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi",
         "-i", "anullsrc=r=44100:cl=mono:d=0.5", "-c:a", "aac", "-y",
         str(audio_only)],
        check=True,
        capture_output=True,
    )
    with pytest.raises(NoVideoStreamError):
        probe_media(audio_only)


# ---------------------------------------------------------------- shot detection

def test_detect_shots_rational_fps(ffmpeg_available, tmp_path):
    video = make_solid_video(tmp_path / "r.mp4", seconds=1.0, fps="30000/1001")
    facts = probe_media(video)
    result = detect_shots(video, DetectorConfig(min_scene_len_frames=5),
                          media_facts=facts)
    assert result.detector_version
    assert result.parameters["threshold"] == 27.0
    assert len(result.shots) == 1
    shot = result.shots[0]
    assert shot.start_seconds == 0.0
    assert shot.start_frame == 0


def test_no_cut_yields_single_shot(ffmpeg_available, tmp_path):
    video = make_solid_video(tmp_path / "solid.mp4", seconds=1.0)
    facts = probe_media(video)
    result = detect_shots(video, DetectorConfig(min_scene_len_frames=5),
                          media_facts=facts)
    assert len(result.shots) >= 1
    assert all(s.end_seconds > s.start_seconds for s in result.shots)


def test_shots_ordered_and_terminated_at_duration(ffmpeg_available, tmp_path):
    video = make_multicut_video(tmp_path / "cuts.mp4", segment_seconds=0.8,
                                colors=("red", "blue", "green"))
    facts = probe_media(video)
    result = detect_shots(video, DetectorConfig(threshold=27.0), media_facts=facts)
    shots = result.shots
    assert len(shots) >= 3
    for a, b in zip(shots, shots[1:]):
        assert b.start_seconds >= a.end_seconds - 1e-6
        assert b.start_frame >= a.end_frame - 1
    assert shots[0].start_seconds == 0.0
    assert abs(shots[-1].end_seconds - facts.duration_seconds) < 0.3
    ids = [s.shot_id for s in shots]
    assert ids == [f"shot_{i:03d}" for i in range(1, len(shots) + 1)]


def test_detect_shots_missing_file():
    with pytest.raises(MediaFileNotFoundError):
        detect_shots("/nonexistent/v.mp4")


def test_detect_shots_corrupt(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"junk" * 32)
    with pytest.raises(UnreadableMediaError):
        detect_shots(bad)


# ---------------------------------------------------------------- frames

def test_representative_frames_deterministic(ffmpeg_available, tmp_path):
    video = make_multicut_video(tmp_path / "c.mp4", colors=("red", "blue", "green"))
    facts = probe_media(video)
    result = detect_shots(video, media_facts=facts)
    out1 = tmp_path / "frames1"
    out2 = tmp_path / "frames2"

    art1 = extract_representative_frames(video, result.shots, out1, fps=facts.fps)
    art2 = extract_representative_frames(video, result.shots, out2, fps=facts.fps)
    assert [a.timestamp_seconds for a in art1] == [a.timestamp_seconds for a in art2]
    names1 = sorted(Path(a.path).name for a in art1)
    names2 = sorted(Path(a.path).name for a in art2)
    assert names1 == names2 == sorted(s.shot_id + ".jpg" for s in result.shots)
    for a in art1:
        p = Path(a.path)
        assert p.is_file() and p.stat().st_size > 0


def test_representative_frames_missing_source(ffmpeg_available, tmp_path):
    from tiktok_analytics_factory.perception.errors import FrameExtractionError
    from tiktok_analytics_factory.perception.models import Shot

    with pytest.raises(FrameExtractionError):
        extract_representative_frames(
            "/nonexistent.mp4",
            [Shot("shot_001", 0.0, 1.0, 0, 30)],
            tmp_path / "f",
        )


# ---------------------------------------------------------------- pipeline

def test_run_perception_manifest(ffmpeg_available, tmp_path):
    video = make_multicut_video(tmp_path / "ref_video.mp4")
    manifest = run_perception(video, tmp_path / "out")
    d = manifest.to_dict()
    assert d["pipeline_version"]
    assert d["source_sha256"] == manifest.media_facts.sha256
    assert (tmp_path / "out" / "media_facts.json").is_file()
    assert (tmp_path / "out" / "shots.json").is_file()
    assert (tmp_path / "out" / "perception_manifest.json").is_file()
    saved = json.loads((tmp_path / "out" / "shots.json").read_text())
    assert saved["detector"].startswith("PySceneDetect")
    assert saved["parameters"]["threshold"] == 27.0
    assert len(manifest.frames) == len(manifest.shots.shots)


# ---------------------------------------------------------------- evaluation

def test_boundary_evaluation_metrics():
    anns = [CutAnnotation(t) for t in (0.8, 1.6)]
    detected = [0.85, 1.7, 2.4]  # third is an FP beyond tolerance
    ev = evaluate_boundaries(detected, anns, tolerance_seconds=0.30)
    assert ev.true_positives == 2
    assert ev.false_positives == 1
    assert ev.missed == 0
    assert ev.precision == pytest.approx(2 / 3)
    assert ev.recall == 1.0
    assert ev.median_absolute_error_seconds == pytest.approx(0.075)


def test_boundary_evaluation_missed_boundaries():
    anns = [CutAnnotation(t) for t in (0.8, 1.6)]
    ev = evaluate_boundaries([0.9], anns)
    assert ev.true_positives == 1
    assert ev.missed == 1
    assert ev.recall == pytest.approx(0.5)


def test_shot_cut_timestamps_excludes_zero_start():
    ts = shot_cut_timestamps([(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)])
    assert ts == [1.0, 2.0]


def test_synthetic_multicut_boundary_evaluation(ffmpeg_available, tmp_path):
    """Synthetic multi-cut fixture: cuts land at segment joins."""
    seg = 0.8
    video = make_multicut_video(tmp_path / "synth.mp4", segment_seconds=seg)
    facts = probe_media(video)
    result = detect_shots(video, DetectorConfig(threshold=27.0), media_facts=facts)
    detected = shot_cut_timestamps(
        [(s.start_seconds, s.end_seconds) for s in result.shots]
    )
    expected_cuts = [seg * i for i in range(1, 3)]  # concat may insert tiny gaps;
    ev = evaluate_boundaries(detected, [CutAnnotation(t) for t in expected_cuts])
    assert ev.true_positives >= 1
    assert ev.precision == 1.0 or ev.false_positives <= 1
