"""Helpers to generate tiny deterministic synthetic MP4 fixtures with ffmpeg.

These are used by perception tests: no TikTok or Gemini network access.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg fixture generation failed: {proc.stderr}")


def make_solid_color_video(
    path: Path,
    *,
    duration: float = 2.0,
    color: str = "red",
    fps: str = "30",
    size: str = "64x64",
    with_audio: bool = False,
) -> None:
    """One constant-color video, no cuts."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i",
        f"color=c={color}:s={size}:r={fps}:d={duration}",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:d={duration}"]
    cmd += ["-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(path))
    _run(cmd)


def make_multicut_video(
    path: Path,
    colors: list[str] | None = None,
    segment_duration: float = 0.5,
    fps: int = 30,
) -> list[float]:
    """Concatenate solid-color segments -> known hard cuts.

    Returns the ground-truth cut times in seconds.
    """
    if colors is None:
        colors = ["red", "blue", "green", "black", "white", "yellow"]
    workdir = path.parent
    workdir.mkdir(parents=True, exist_ok=True)

    cut_times: list[float] = []
    concat_list = workdir / "concat.txt"
    lines = []
    t = 0.0
    for i, color in enumerate(colors):
        seg = workdir / f"seg_{i}.mp4"
        make_solid_color_video(seg, duration=segment_duration, color=color, fps=str(fps))
        lines.append(f"file '{seg}'")
        if i > 0:
            cut_times.append(round(t, 6))
        t += segment_duration
    concat_list.write_text("\n".join(lines) + "\n")

    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy", str(path),
    ])
    for i in range(len(colors)):
        seg = workdir / f"seg_{i}.mp4"
        seg.unlink()
    return cut_times


def make_no_audio_video(path: Path) -> None:
    make_solid_color_video(path, duration=1.5, color="purple", with_audio=False)


def make_corrupt_file(path: Path) -> None:
    path.write_bytes(b"this is not a video file at all")
