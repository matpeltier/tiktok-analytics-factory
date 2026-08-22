"""End-to-end deterministic perception pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import PIPELINE_VERSION
from .models import PerceptionConfig, PerceptionManifest
from .frames import extract_representative_frames
from .probe import probe_media
from .shots import detect_shots


def run_perception(
    video_path: str | Path,
    output_dir: str | Path,
    config: PerceptionConfig | None = None,
) -> PerceptionManifest:
    """Run probing, shot detection and frame extraction for one video.

    Writes ``media_facts.json``, ``shots.json`` and ``frames/shot_*.jpg``
    under ``output_dir`` and returns the manifest.
    """
    cfg = config or PerceptionConfig()
    src = Path(video_path)
    out = Path(output_dir)
    frames_dir = out / "frames"

    facts = probe_media(src)
    shots = detect_shots(src, cfg)
    artifacts = extract_representative_frames(src, shots, frames_dir)

    (out / "media_facts.json").write_text(
        json.dumps(facts.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    (out / "shots.json").write_text(
        json.dumps(shots.to_dict(), indent=2) + "\n", encoding="utf-8"
    )

    manifest = PerceptionManifest(
        pipeline_version=PIPELINE_VERSION,
        video_sha256=facts.sha256,
        generated_at=datetime.now(timezone.utc).isoformat(),
        config=cfg.to_dict(),
        media_facts=facts,
        shots=shots,
        frames=artifacts,
    )
    (out / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    return manifest
