"""Deterministic representative-frame extraction via ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .errors import FrameExtractionError
from .models import FrameArtifact, Shot, ShotDetectionResult

# Deterministic fallback offsets (seconds before the midpoint) tried in order
# when the midpoint frame cannot be decoded.
_FALLBACK_OFFSETS = (0.0, 0.1, 0.5)


def extract_representative_frames(
    video_path: str | Path,
    shots: ShotDetectionResult | list[Shot],
    output_dir: str | Path,
) -> list[FrameArtifact]:
    """Extract one JPEG frame per shot at the temporal midpoint.

    Filenames are stable and derived from shot IDs: ``shot_001.jpg``.
    If the midpoint frame cannot be decoded, earlier deterministic timestamps
    are tried; if all fail, :class:`FrameExtractionError` is raised.
    """
    if shutil.which("ffmpeg") is None:
        raise FrameExtractionError("ffmpeg binary not found on PATH")

    shot_list = (
        [s for s in shots.shots] if isinstance(shots, ShotDetectionResult) else list(shots)
    )
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    src = str(video_path)

    artifacts: list[FrameArtifact] = []
    for shot in shot_list:
        midpoint = (shot.start_seconds + shot.end_seconds) / 2.0
        last_error: Exception | None = None
        extracted_path: Path | None = None
        chosen_ts = midpoint

        for offset in _FALLBACK_OFFSETS:
            ts = round(shot.start_seconds + max(0.0, (shot.end_seconds - shot.start_seconds) / 2.0 - offset), 6)
            target = out_dir / f"{shot.shot_id}.jpg"
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{ts:.6f}",
                "-i",
                src,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(target),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode == 0 and target.exists() and target.stat().st_size > 0:
                extracted_path = target
                chosen_ts = ts
                break
            if target.exists():
                target.unlink()
            last_error = FrameExtractionError(
                f"ffmpeg failed for {shot.shot_id} at {ts:.3f}s: {proc.stderr.strip()}"
            )

        if extracted_path is None:
            raise FrameExtractionError(
                f"could not decode any representative frame for {shot.shot_id}: {last_error}"
            )
        artifacts.append(
            FrameArtifact(
                shot_id=shot.shot_id,
                path=str(extracted_path),
                timestamp_seconds=chosen_ts,
            )
        )
    return artifacts
