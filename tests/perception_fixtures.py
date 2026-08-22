"""Helpers to build tiny deterministic MP4 fixtures with local ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ffmpeg = shutil.which("ffmpeg")
ffprobe = shutil.which("ffprobe")

pytestmark = pytest.mark.skipif(
    ffmpeg is None, reason="ffmpeg/ffprobe not available on PATH"
)


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"fixture generation failed: {proc.stderr[-800:]}")


def make_solid_video(path: Path, seconds: float = 1.0, with_audio: bool = True,
                     fps: str | None = None) -> Path:
    """A single-color video with (optionally) a silent audio track: no cuts."""
    cmd = [ffmpeg, "-v", "error", "-f", "lavfi",
           "-i", f"color=c=red:s=64x64:d={seconds}"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    if fps:
        cmd += ["-r", fps]
    cmd += ["-y", str(path)]
    _run(cmd)
    return path


def make_multicut_video(path: Path, segment_seconds: float = 0.8,
                        colors=("red", "blue", "green")) -> Path:
    """Concatenated solid-color segments -> known hard cuts between them."""
    parts: list[Path] = []
    for i, color in enumerate(colors):
        part = path.with_name(f"{path.stem}_part{i}.mp4")
        _run([
            ffmpeg, "-v", "error", "-f", "lavfi",
            "-i", f"color=c={color}:s=64x64:d={segment_seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(part),
        ])
        parts.append(part)
    listfile = path.with_name(f"{path.stem}_list.txt")
    listfile.write_text("".join(f"file '{p}'\n" for p in parts))
    _run([
        ffmpeg, "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-c", "copy", "-y", str(path),
    ])
    for p in parts:
        p.unlink()
    listfile.unlink()
    return path


@pytest.fixture
def solid_video(tmp_path):
    return make_solid_video(tmp_path / "solid.mp4")


@pytest.fixture
def multicut_video(tmp_path):
    return make_multicut_video(tmp_path / "multicut.mp4")
