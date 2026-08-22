"""Deterministic representative-frame extraction per shot."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .errors import FFprobeUnavailableError, FrameExtractionError
from .models import FrameArtifact, Shot


def _ffmpeg_binary() -> str:
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise FFprobeUnavailableError("ffmpeg executable not found on PATH")
    return binary


def _frame_index_for_timestamp(shot: Shot, fps: float) -> int:
    midpoint = (shot.start_seconds + shot.end_seconds) / 2.0
    return max(shot.start_frame, min(shot.end_frame - 1,
                                     int(round(midpoint * fps))))


def representative_timestamp(shot: Shot) -> float:
    """Deterministic timestamp: temporal midpoint of the shot."""
    return round((shot.start_seconds + shot.end_seconds) / 2.0, 6)


def extract_representative_frames(
    video_path: str | Path,
    shots: list[Shot],
    output_dir: str | Path,
    fps: float | None = None,
    quality: int = 2,
) -> list[FrameArtifact]:
    """Extract one JPEG per shot at its temporal midpoint.

    If the exact midpoint frame cannot be decoded, extraction is retried at
    progressively earlier timestamps within the shot before failing loudly.
    """
    path = Path(video_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    binary = _ffmpeg_binary()

    artifacts: list[FrameArtifact] = []
    for shot in shots:
        ts = representative_timestamp(shot)
        out_path = out_dir / f"{shot.shot_id}.jpg"
        frame_index = (
            _frame_index_for_timestamp(shot, fps)
            if fps is not None and fps > 0
            else 0
        )
        extracted = False
        last_err = ""
        # Deterministic retry ladder: midpoint, then earlier offsets inside shot.
        span = max(shot.end_seconds - shot.start_seconds, 0.04)
        for frac in (0.5, 0.4, 0.25, 0.1):
            candidate = round(shot.start_seconds + span * frac, 6)
            command = [
                binary,
                "-v", "error",
                "-ss", f"{candidate:.6f}",
                "-i", str(path),
                "-frames:v", "1",
                "-q:v", str(quality),
                "-y",
                str(out_path),
            ]
            proc = subprocess.run(command, capture_output=True, text=True, timeout=60)
            if proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0:
                extracted = True
                ts = candidate
                break
            last_err = proc.stderr.strip()
        if not extracted:
            raise FrameExtractionError(
                f"failed to extract a representative frame for {shot.shot_id} "
                f"from {path}: {last_err}"
            )
        artifacts.append(
            FrameArtifact(
                shot_id=shot.shot_id,
                path=str(out_path),
                timestamp_seconds=ts,
                frame_index=frame_index,
            )
        )
    return artifacts
