"""Deterministic hard-cut/scene boundary detection via PySceneDetect."""

from __future__ import annotations

from pathlib import Path

from .errors import (
    MediaFileNotFoundError,
    SceneDetectorUnavailableError,
    UnreadableMediaError,
)
from .models import DetectorConfig, Shot, ShotDetectionResult

DETECTOR_NAME = "PySceneDetect.ContentDetector"


def _detector_version() -> str:
    try:
        import scenedetect
    except ImportError as exc:
        raise SceneDetectorUnavailableError(
            "scenedetect is not installed; install it to run shot detection"
        ) from exc
    return getattr(scenedetect, "__version__", "unknown")


def detect_shots(
    video_path: str | Path,
    config: DetectorConfig | None = None,
    media_facts=None,
) -> ShotDetectionResult:
    """Detect hard cuts with ContentDetector.

    ``media_facts`` may be passed (a :class:`MediaFacts`) to avoid re-probing.
    """
    path = Path(video_path)
    if not path.is_file():
        raise MediaFileNotFoundError(f"media file does not exist: {path}")
    config = config or DetectorConfig()

    try:
        import scenedetect
        from scenedetect.detectors import ContentDetector
    except ImportError as exc:
        raise SceneDetectorUnavailableError(str(exc)) from exc

    version = _detector_version()
    try:
        video = scenedetect.open_video(str(path))
    except Exception as exc:  # scenedetect raises assorted errors on corrupt input
        raise UnreadableMediaError(f"cannot open {path} for scene detection: {exc}") from exc

    detector_kwargs: dict = {"threshold": config.threshold}
    if hasattr(ContentDetector, "__init__") and "min_scene_len" in (
        ContentDetector.__init__.__doc__ or ""
    ):
        pass  # min_scene_len handled below via frame_size for compat
    if config.min_scene_len_frames is not None:
        detector_kwargs["min_scene_len"] = config.min_scene_len_frames

    scene_manager = scenedetect.SceneManager()
    scene_manager.add_detector(ContentDetector(**detector_kwargs))
    try:
        video_fps = video.frame_rate
        scene_manager.detect_scenes(video)
        scene_list = scene_manager.get_scene_list()
    except Exception as exc:
        raise UnreadableMediaError(f"scene detection failed on {path}: {exc}") from exc

    fps = video_fps or (media_facts.fps if media_facts else None) or 30.0
    duration = media_facts.duration_seconds if media_facts else None

    shots: list[Shot] = []
    for i, (start, end) in enumerate(scene_list, start=1):
        start_s = getattr(start, "seconds", None)
        if start_s is None:
            start_s = start.get_seconds()
        end_s = getattr(end, "seconds", None)
        if end_s is None:
            end_s = end.get_seconds()
        start_f = getattr(start, "frame_num", None)
        if start_f is None:
            start_f = start.get_frames()
        end_f = getattr(end, "frame_num", None)
        if end_f is None:
            end_f = end.get_frames()
        shots.append(
            Shot(
                shot_id=f"shot_{i:03d}",
                start_seconds=round(start_s, 6),
                end_seconds=round(end_s, 6),
                start_frame=start_f,
                end_frame=end_f,
            )
        )

    # No cut detected -> one shot spanning the whole video.
    if not shots:
        total = duration
        total_frames = int(round((total or 0) * fps)) if total is not None else 0
        shots = [
            Shot(shot_id="shot_001", start_seconds=0.0,
                 end_seconds=round(total, 6) if total is not None else 0.0,
                 start_frame=0, end_frame=total_frames)
        ]
    else:
        # First shot must begin at zero.
        shots[0].start_seconds = 0.0
        shots[0].start_frame = 0
        # Last shot must terminate at the probed duration when known.
        if duration is not None and abs(shots[-1].end_seconds - duration) > 0.5 / fps:
            shots[-1].end_seconds = round(duration, 6)

    return ShotDetectionResult(
        detector=DETECTOR_NAME,
        detector_version=version,
        parameters=config.to_parameters(),
        shots=shots,
    )
