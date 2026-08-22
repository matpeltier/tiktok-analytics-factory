"""Deterministic hard-cut shot detection using PySceneDetect."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import SceneDetectorUnavailableError
from .models import PerceptionConfig, Shot, ShotDetectionResult
from .probe import probe_media

DETECTOR_NAME = "ContentDetector"

try:  # pragma: no cover - trivial version capture
    import scenedetect

    _SCENEDETECT_VERSION = scenedetect.__version__
except ImportError:
    scenedetect = None
    _SCENEDETECT_VERSION = None


def detect_shots(
    video_path: str | Path,
    config: PerceptionConfig | None = None,
) -> ShotDetectionResult:
    """Detect hard visual cuts and return ordered, non-overlapping shots.

    Guarantees:
    - first shot starts at 0.0;
    - last shot ends at the probed media duration (frame rounding absorbed);
    - a video with no detected cuts yields exactly one full-length shot;
    - timestamps are ordered and non-overlapping.
    """
    if scenedetect is None or _SCENEDETECT_VERSION is None:
        raise SceneDetectorUnavailableError(
            "PySceneDetect is not installed; pip install scenedetect"
        )
    cfg = config or PerceptionConfig()
    if cfg.detector != DETECTOR_NAME:
        raise SceneDetectorUnavailableError(
            f"unsupported detector {cfg.detector!r}; only {DETECTOR_NAME!r} is implemented"
        )

    from scenedetect import ContentDetector, SceneManager, open_video

    facts = probe_media(video_path)
    duration = facts.duration_seconds
    fps = facts.fps if facts.fps > 0 else 30.0

    video = open_video(str(video_path))
    scene_manager = SceneManager()
    scene_manager.add_detector(
        ContentDetector(
            threshold=cfg.threshold, min_scene_len=cfg.min_scene_len_frames
        )
    )
    if cfg.downscale_factor:
        scene_manager.downscale_factor = cfg.downscale_factor
    scene_manager.detect_scenes(video)

    cuts_seconds: list[float] = []
    for start, _end in scene_manager.get_scene_list():
        # The boundary time is the start of the *next* scene.
        cut = start.seconds
        cuts_seconds.append(round(cut, 6))

    shots = _build_shots(cuts_seconds, duration, fps)
    return ShotDetectionResult(
        detector=DETECTOR_NAME,
        detector_version=_SCENEDETECT_VERSION,
        parameters={
            "threshold": cfg.threshold,
            "min_scene_len_frames": cfg.min_scene_len_frames,
            "downscale_factor": cfg.downscale_factor,
        },
        shots=shots,
        duration_seconds=duration,
    )


def _build_shots(
    cuts_seconds: list[float], duration: float, fps: float
) -> list[Shot]:
    """Turn sorted cut times into validated shots."""
    cuts = sorted(c for c in cuts_seconds if 0.0 < c < duration - 1e-9)

    boundaries = [0.0, *cuts, duration]
    shots: list[Shot] = []
    for i in range(len(boundaries) - 1):
        start_s = boundaries[i]
        end_s = boundaries[i + 1]
        start_f = round(start_s * fps)
        end_f = round(end_s * fps)
        if i == len(boundaries) - 2:
            end_f = max(end_f, round(duration * fps))
        if end_s - start_s <= 0:
            continue  # degenerate after clamping; skip silently-empty sliver
        shots.append(
            Shot(
                shot_id=f"shot_{len(shots) + 1:03d}",
                start_seconds=round(start_s, 6),
                end_seconds=round(end_s, 6),
                start_frame=start_f,
                end_frame=end_f,
            )
        )
    if not shots:
        # No cut detected / degenerate boundaries: one shot spanning the video.
        shots.append(
            Shot(
                shot_id="shot_001",
                start_seconds=0.0,
                end_seconds=duration,
                start_frame=0,
                end_frame=round(duration * fps),
            )
        )
    return shots


def validate_shots(shots: list[Shot]) -> None:
    """Assert ordering/non-overlap invariants; raises ValueError otherwise."""
    prev_end = -1.0
    prev_id = ""
    for s in shots:
        assert s.start_seconds >= prev_end - 1e-9, (
            f"{s.shot_id} overlaps {prev_id}"
        )
        assert s.end_seconds > s.start_seconds, f"{s.shot_id} has empty span"
        prev_end, prev_id = s.end_seconds, s.shot_id
