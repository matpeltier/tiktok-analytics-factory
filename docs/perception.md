# Deterministic perception layer

The perception layer supplies the facts a VLM should not guess: authoritative
media metadata, hard-cut/shot boundaries, and representative visual artifacts.
It is deliberately **model-free** — no Gemini, Whisper, OCR, or LLM.

```text
video.mp4
  -> ffprobe        -> media_facts.json
  -> PySceneDetect  -> shots.json
  -> ffmpeg         -> frames/shot_XXX.jpg
                    -> perception_manifest.json
```

## API

```python
from tiktok_analytics_factory.perception import (
    probe_media,                  # (video_path) -> MediaFacts
    detect_shots,                 # (video_path, config) -> ShotDetectionResult
    extract_representative_frames,# (video_path, shots, output_dir) -> [FrameArtifact]
    run_perception,               # (video_path, output_dir, config) -> PerceptionManifest
    DetectorConfig,
)
```

All return types are typed dataclasses (`models.py`); nested dictionaries are
never passed around unvalidated. `run_perception` persists:

```text
data/derived/<video_id>/perception/<pipeline_version>/
  media_facts.json
  shots.json
  perception_manifest.json
  frames/shot_001.jpg ...
```

## Media facts

`ffprobe` is the authoritative source for duration, width/height, aspect ratio,
frame rate (kept in both original rational form and normalized float), frame
count, codecs, container format, and bit rate. File size is from the filesystem,
the source MP4 SHA-256 is computed over the raw bytes, and the ffprobe version,
exact probe command, and UTC processing timestamp are persisted as provenance.

An absent audio stream is recorded as `has_audio=false` / `audio_codec=null`.
It is a **valid media fact**, not an error. Missing fields are surfaced as
`null` — never filled by a model.

## Shot detection

- Detector: `PySceneDetect.ContentDetector` (deterministic content-value
  thresholding on decoded frames).
- Default parameters: `threshold=27.0`, `min_scene_len_frames=15`
  (scenedetect default), `downscale_factor=None` (library default).
- Detector name, version, and parameters are stored in `shots.json`.

Guarantees enforced by the module:

- shots are ordered and non-overlapping;
- the first shot starts at 0.0 / frame 0;
- the last shot ends at the probed media duration within normal frame-rounding
  tolerance;
- a video with **no detected cut yields exactly one shot** spanning the whole
  video, never an empty list;
- shot IDs (`shot_001`, ...) drive generated filenames — no random UUIDs.

## Representative frames

One JPEG per shot at the temporal midpoint (deterministic). If the exact
midpoint cannot be decoded, extraction retries at progressively earlier
deterministic offsets inside the shot before failing loudly
(`FrameExtractionError`). No redundant per-frame dumps are produced.

## Determinism

Given identical source bytes, identical tool versions, and identical detector
parameters, media facts, boundaries, and representative-frame timestamps are
reproducible. Only provenance timestamps vary between runs.

## Error handling

Explicit exceptions (`errors.py`): missing file, unreadable/corrupt media, no
video stream, ffprobe/ffmpeg unavailable, scene detector unavailable, frame
extraction failure. Failures raise; there are no silent fallbacks.

## Boundary evaluation

Detected internal cut timestamps are evaluated against a manual annotation of
**hard visual cuts** with greedy nearest-neighbor matching inside a documented
tolerance (default **±0.30 s**), reporting TP / FP / missed / precision /
recall / F1 and median absolute timing error for matched pairs
(`evaluation.evaluate_boundaries`). This evaluates deterministic cut detection
only — it makes no claim about semantic scene changes that are not hard cuts.

### Reference-video evaluation (canonical TikTok 6718335390845095173)

The canonical 10.495 s reference video from issue #2 was recovered (re-ingested
after the local CDN snapshot URLs expired) and stored at
`data/raw/6718335390845095173/video.mp4`. Its perception artifacts live in
`data/derived/6718335390845095173/perception/v1/`:
`media_facts.json`, `shots.json`, `perception_manifest.json`,
`hard_cut_annotation.json`, `boundary_evaluation.json`, and
`frames/shot_001.jpg … shot_010.jpg`.

Hard-cut annotation method: manual review of before/after frames at every
candidate boundary plus a 4 fps contact sheet covering the full video; a
boundary counts as a hard visual cut only when both sides are clearly
different scenes. Nine hard cuts were annotated (0.50, 1.13, 3.40, 4.20,
4.93, 5.70, 6.60, 7.57, 8.37 s); several coincide with whip-pan blur
transitions but present as abrupt cuts.

Result with default parameters (`threshold=27.0`, ±0.30 s tolerance):
TP=9, FP=0, missed=0, precision = recall = F1 = 1.0, median absolute timing
error = 0.000 s. A tiny synthetic fixture with known cuts remains in the test
suite as an additional deterministic check only; it does not replace the
canonical reference video.

## Known limitations

- ContentDetector measures low-level pixel change: gradual transitions,
  fades, whip pans, or heavy motion may be missed or over-segmented. TikTok
  jump-cut style edits are usually detected well.
- Very short shots below `min_scene_len_frames` (15 frames) are merged into
  neighbors.
- Frame count uses `-count_frames` (full decode) for accuracy at the cost of a
  slower probe; falls back to container-reported `nb_frames` when decoding is
  unavailable.
- Variable-frame-rate sources can shift boundary timestamps slightly; the last
  shot end is clamped to the probed duration.
