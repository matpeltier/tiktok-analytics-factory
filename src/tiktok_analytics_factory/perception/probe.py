"""ffprobe-based deterministic media probing."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from .errors import (
    CorruptMediaError,
    FFprobeUnavailableError,
    NoVideoStreamError,
    VideoNotFoundError,
)
from .models import MediaFacts


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe_version() -> str:
    if shutil.which("ffprobe") is None:
        raise FFprobeUnavailableError(
            "ffprobe binary not found on PATH; install ffmpeg/ffprobe."
        )
    out = subprocess.run(
        ["ffprobe", "-version"], capture_output=True, text=True, check=True
    ).stdout
    first = out.splitlines()[0].strip()
    # e.g. "ffprobe version 6.1.1-3ubuntu5 Copyright ..."
    parts = first.split()
    return parts[2] if len(parts) > 2 else first


def _reduce_ratio(ratio_str: str | None) -> tuple[str, float] | None:
    """Reduce a display ratio like '16:9' or '640:360' to a label + float."""
    if not ratio_str or ":" not in ratio_str:
        return None
    num, den = ratio_str.split(":", 1)
    try:
        frac = Fraction(int(num), int(den))
    except (ValueError, ZeroDivisionError):
        return None
    return f"{frac.numerator}:{frac.denominator}", float(frac)


def _parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def probe_media(video_path: str | Path) -> MediaFacts:
    """Return authoritative media facts for ``video_path`` using ffprobe.

    Raises explicit errors for missing files, corrupt media, missing ffprobe,
    and containers without a video stream. An absent audio stream is a valid
    fact, not an error.
    """
    path = Path(video_path)
    if not path.exists():
        raise VideoNotFoundError(f"video file does not exist: {path}")
    if not path.is_file():
        raise CorruptMediaError(f"path is not a regular file: {path}")

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise CorruptMediaError(
            f"ffprobe failed for {path} (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CorruptMediaError(f"ffprobe returned invalid JSON: {exc}") from exc

    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not video_streams:
        raise NoVideoStreamError(f"no video stream found in {path}")
    v = video_streams[0]
    fmt = data.get("format", {})

    duration = _parse_float(fmt.get("duration")) or _parse_float(v.get("duration"))
    if duration is None:
        raise CorruptMediaError(f"could not determine duration for {path}")

    aspect = _reduce_ratio(v.get("display_aspect_ratio")) or _reduce_ratio(
        f"{v.get('width')}:{v.get('height')}"
    ) or ("unknown", 0.0)

    fps_rational = v.get("r_frame_rate") or v.get("avg_frame_rate") or "0/1"
    fps = 0.0
    if "/" in fps_rational:
        try:
            fps = float(Fraction(fps_rational))
        except ZeroDivisionError:
            fps = 0.0

    nb_frames = v.get("nb_frames")
    frame_count = int(nb_frames) if nb_frames and nb_frames.isdigit() else None
    bit_rate = fmt.get("bit_rate") or v.get("bit_rate")
    bit_rate_int = int(bit_rate) if bit_rate and str(bit_rate).isdigit() else None

    return MediaFacts(
        duration_seconds=duration,
        width=int(v["width"]),
        height=int(v["height"]),
        aspect_ratio_label=aspect[0],
        aspect_ratio_float=aspect[1],
        fps_rational=fps_rational,
        fps=fps,
        frame_count=frame_count,
        video_codec=v.get("codec_name", "unknown"),
        audio_codec=audio_streams[0].get("codec_name") if audio_streams else None,
        has_audio=bool(audio_streams),
        container_format=fmt.get("format_name", "unknown"),
        bit_rate=bit_rate_int,
        file_size_bytes=int(path.stat().st_size),
        sha256=sha256_file(path),
        ffprobe_version=ffprobe_version(),
        probed_at=_utc_now_iso(),
    )


def parse_fps_rational(rational: str) -> Fraction:
    """Parse an FPS rational such as '30000/1001' into a Fraction."""
    frac = Fraction(rational)
    if frac <= 0:
        raise CorruptMediaError(f"non-positive frame rate: {rational}")
    return frac
