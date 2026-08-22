# Perception layer (deterministic)

Model-free facts for one ingested MP4: media probing (ffprobe), hard-cut shot
segmentation (PySceneDetect `ContentDetector`), and representative frames
(ffmpeg). No Gemini, Whisper, OCR, or any LLM is involved.

## Pipeline

```text
video.mp4 -> ffprobe   -> media_facts.json
          -> PySceneDetect -> shots.json
          -> ffmpeg    -> frames/shot_XXX.jpg
```

Output layout:

```text
data/derived/<video_id>/perception/<pipeline_version>/
  media_facts.json
  shots.json
  manifest.json
  frames/shot_001.jpg ...
```

## API

```python
probe_media(video_path) -> MediaFacts
detect_shots(video_path, config) -> ShotDetectionResult
extract_representative_frames(video_path, shots, output_dir) -> list[FrameArtifact]
run_perception(video_path, output_dir, config) -> PerceptionManifest
```

All artifacts serialize from typed dataclasses (`perception/models.py`);
consumers never parse unvalidated dicts. `run_perception` also emits
`manifest.json` for downstream consumption by issue #6 without notebook state.

## Detector assumptions and parameters

- `ContentDetector` with default `threshold=27.0`,
  `min_scene_len_frames=15`, `downscale_factor=4` (see `PerceptionConfig`).
- The detector finds *hard visual cuts* only; gradual/semantic scene changes,
  fades, and whip pans may be missed or split arbitrarily.
- Invariants enforced in code: first shot starts at 0.0, last shot ends at the
  probed duration (frame rounding absorbed), timestamps ordered and
  non-overlapping, no-cut videos yield exactly one full-length shot.
- Representative frame = temporal midpoint of each shot; if that frame cannot
  be decoded, deterministic earlier offsets (0.1s, then 0.5s) are tried before
  failing loudly.
- Provenance persisted: source SHA-256, ffprobe version, detector name/version,
  detector parameters, processing timestamp.

## Determinism

Identical source bytes + tool versions + parameters reproduce identical facts,
boundaries, and frame timestamps. Filenames derive from stable shot IDs.

## Error handling

Explicit exceptions (`perception/errors.py`) for: missing file, corrupt media,
no video stream, ffprobe unavailable, detector unavailable, frame extraction
failure. An absent audio stream is a recorded fact (`has_audio=false`), not a
failure.

## Reference-video evaluation

The canonical reference video from issue #2 was not present in this worktree at
implementation time (`data/raw` empty). Per the issue, evaluation therefore uses
a tiny synthetic fixture video (`tests/perception_video_fixtures.py`) with six
solid-color segments and five known hard cuts at exact 0.5s multiples. Detected
boundaries were evaluated against ground truth with tolerance ±0.30s:
precision = recall = F1 = 1.0, median absolute timing error ≤ one frame period
(see `tests/test_perception.py::TestBoundaryEvaluation`). When the canonical
reference video exists, re-run this evaluation against a hand-reviewed hard-cut
annotation using `evaluate_boundaries(detected, truth, tolerance_seconds=0.30)`.

Known limitations:

- ContentDetector threshold is content-sensitive; very short shots (<15 frames)
  are ignored by design (`min_scene_len`).
- Frame-count-based end-frame values use the probed FPS rational and can differ
  by ±1 frame from decoder-reported indices.
- Cross-fades produce boundaries at fade midpoints, not semantic scene starts.
