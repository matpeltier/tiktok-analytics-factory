# Single-video TikTok ingestion

## Usage

```bash
uv pip install -e '.[ingestion,dev]'
python -m tiktok_analytics_factory.ingestion ingest \
  --url 'https://www.tiktok.com/@user/video/VIDEO_ID' \
  --output-root data/raw
```

On success it prints the video ID and artifact directory; on failure it exits
non-zero and prints a structured error (`category`, `message`, `detail`) on
stderr.

## Output layout

```text
data/raw/<video_id>/
  video.mp4                    # immutable downloaded media
  metadata.raw.json            # unmodified collector payload
  metadata.normalized.json     # normalized contract (unknown = null)
  manifest.json                # provenance: hashes, collectors, timestamps, failures
```

`data/**` is Git-ignored. Never commit real MP4s.

## Collector order

1. `pyktok` (preferred) — public metadata + media via `pyktok`.
2. `yt-dlp` (fallback) — public page metadata + media.

The successful collector is recorded in `manifest.json`. **No silent
fallback**: every failed attempt is persisted in
`manifest.fallback_or_error_notes`; if all fail, a structured error is
returned (no fake success records).

Install extras with `uv pip install -e '.[ingestion]'`. If a dependency is
missing you get category `collector_dependency_unavailable`.

## Unknown-value convention

Unknown/unavailable metadata values are JSON `null` in
`metadata.normalized.json`. Zero is never used to mean unknown.

## Idempotency

- Re-running the same URL reuses an identical-hash MP4 (never overwrites).
- A different download for the same video ID aborts with
  `artifact_mismatch`.
- `--force-new-observation` appends timestamped metadata snapshots
  (engagement counts change over time); raw MP4 stays immutable.

## Error categories

| Category | Meaning |
|---|---|
| `invalid_url` | Not a TikTok URL / no ID extractable |
| `video_unavailable` | Private, deleted, or region-locked |
| `download_failure` | Media fetch failed |
| `metadata_parse_failure` | Payload missing/unparseable |
| `file_write_failure` | Disk write error |
| `collector_dependency_unavailable` | pyktok/yt-dlp missing |
| `artifact_mismatch` | Existing MP4 differs from new download |

## Common failure modes

- TikTok rate-limits or bot-challenges public endpoints — retry later or use
  a different network; no proxies are used by design.
- Short links (`vm.tiktok.com/...`) resolve only at request time.
- pyktok can break when TikTok changes its API; yt-dlp is the fallback.

## Optional live integration check

CI must not depend on TikTok availability. Manually run:

```bash
pytest -m integration tests/test_integration_live.py
```
