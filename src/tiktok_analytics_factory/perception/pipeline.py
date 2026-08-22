"""Top-level perception pipeline: probe -> detect shots -> extract frames."""

from __future__ import annotations

import json
from pathlib import Path

from .frames import extract_representative_frames
from .models import PIPELINE_VERSION, DetectorConfig, PerceptionManifest
from .probing import probe_media
from .shots import detect_shots


def video_id_for(video_path: str | Path) -> str:
    """Stable video id derived from the source filename stem."""
    return Path(video_path).stem


def run_perception(
    video_path: str | Path,
    output_dir: str | Path,
    config: DetectorConfig | None = None,
) -> PerceptionManifest:
    """Run the full deterministic perception layer and persist artifacts."""
    path = Path(video_path)
    out_dir = Path(output_dir)
    frames_dir = out_dir / "frames"

    facts = probe_media(path)
    shots_result = detect_shots(path, config, media_facts=facts)
    frames = extract_representative_frames(
        path, shots_result.shots, frames_dir, fps=facts.fps
    )

    manifest = PerceptionManifest(
        pipeline_version=PIPELINE_VERSION,
        video_id=video_id_for(path),
        source_sha256=facts.sha256,
        processed_at=facts.probed_at,
        media_facts=facts,
        shots=shots_result,
        frames=frames,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "media_facts.json").write_text(
        json.dumps(facts.to_dict(), indent=2) + "\n"
    )
    (out_dir / "shots.json").write_text(
        json.dumps(shots_result.to_dict(), indent=2) + "\n"
    )
    (out_dir / "perception_manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2) + "\n"
    )
    return manifest
