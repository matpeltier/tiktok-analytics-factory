"""ffprobe-based deterministic media probing."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .errors import (
    FFprobeUnavailableError,
    MediaFileNotFoundError,
    NoVideoStreamError,
    UnreadableMediaError,
)
from .models import MediaFacts


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def _ffprobe_binary() -> str:
    binary = shutil.which("ffprobe")
    if binary is None:
        raise FFprobeUnavailableError(
            "ffprobe executable not found on PATH; install ffmpeg/ffprobe"
        )
    return binary


def ffprobe_version() -> str:
    binary = _ffprobe_binary()
    result = subprocess.run(
        [binary, "-version"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    first = result.stdout.splitlines()[0].strip() if result.stdout else "unknown"
    return first


def parse_ffprobe_json(raw: str) -> dict:
    """Parse ffprobe JSON output into a dict (isolated for testability)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UnreadableMediaError(f"ffprobe returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise UnreadableMediaError("ffprobe JSON output was not an object")
    return data


def _parse_rational(value: str | None) -> tuple[str | None, float | None]:
    """Return (original rational string, normalized float)."""
    if value is None or value in ("0/0", "N/A"):
        return value if value != "0/0" else None, None
    if "/" in value:
        num_s, den_s = value.split("/", 1)
        try:
            num, den = int(num_s), int(den_s)
        except ValueError:
            return value, None
        if den == 0:
            return value, None
        return value, num / den
    try:
        return value, float(value)
    except ValueError:
        return value, None


def _aspect_ratio(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    from math import gcd

    g = gcd(width, height)
    w, h = width // g, height // g
    if h in (3, 4, 9, 16) and w / h > 2.2:  # common phone ratios kept readable
        pass
    return f"{w}:{h}"


def probe_media(video_path: str | Path) -> MediaFacts:
    """Probe a video with ffprobe and return validated MediaFacts."""
    path = Path(video_path)
    if not path.is_file():
        raise MediaFileNotFoundError(f"media file does not exist: {path}")

    binary = _ffprobe_binary()
    command = [
        binary,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        "-count_frames",
        str(path),
    ]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise UnreadableMediaError(f"ffprobe timed out on {path}") from exc
    if proc.returncode != 0:
        raise UnreadableMediaError(
            f"ffprobe failed (exit {proc.returncode}) on {path}: {proc.stderr.strip()}"
        )

    data = parse_ffprobe_json(proc.stdout)
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    if not video_streams:
        raise NoVideoStreamError(f"no video stream found in {path}")
    vs = video_streams[0]

    duration: float | None
    if fmt.get("duration") is not None:
        try:
            duration = float(fmt["duration"])
        except ValueError:
            duration = None
    elif vs.get("duration") is not None:
        duration = float(vs["duration"])
    else:
        duration = None

    fps_rational, fps = _parse_rational(vs.get("r_frame_rate"))
    avg_fps_rational, avg_fps = _parse_rational(vs.get("avg_frame_rate"))

    frame_count: int | None = None
    if vs.get("nb_read_frames") is not None:
        frame_count = int(vs["nb_read_frames"])
    elif vs.get("nb_frames"):
        try:
            frame_count = int(vs["nb_frames"])
        except ValueError:
            frame_count = None

    bit_rate: int | None = None
    if fmt.get("bit_rate"):
        bit_rate = int(fmt["bit_rate"])

    file_size = path.stat().st_size

    return MediaFacts(
        video_path=str(path),
        duration_seconds=duration,
        width=int(vs["width"]) if vs.get("width") else None,
        height=int(vs["height"]) if vs.get("height") else None,
        aspect_ratio=_aspect_ratio(int(vs["width"]) if vs.get("width") else None,
                                   int(vs["height"]) if vs.get("height") else None),
        fps_rational=fps_rational,
        fps=fps,
        avg_fps_rational=avg_fps_rational,
        avg_fps=avg_fps,
        frame_count=frame_count,
        video_codec=vs.get("codec_name"),
        audio_codec=audio_streams[0].get("codec_name") if audio_streams else None,
        has_audio=bool(audio_streams),
        container_format=fmt.get("format_name"),
        bit_rate=bit_rate,
        file_size_bytes=file_size,
        sha256=sha256_file(path),
        ffprobe_version=ffprobe_version(),
        probe_command=command,
        probed_at=_now_iso(),
    )
