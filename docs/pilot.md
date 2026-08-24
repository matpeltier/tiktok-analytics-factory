# Micro-niche pilot (issue #8)

## Status

The batch pilot infrastructure is implemented and tested end-to-end with fakes.
Its blocking prerequisites are satisfied:

- #6 concluded with the exact decision `validated-for-pilot`
  (reference runs 20260824T080256Z and 20260824T091349Z);
- #7 closed with the explicitly approved `config/pilot_cohort.json`
  (candidate A, approved by matpeltier).

`run-pilot` now wires the validated components by default (ingestion #2,
Performance v0.1 snapshot #3, deterministic perception #5, validated two-pass
decompiler #6, CreativeIR validation and CanonicalIR projection) via
`pipeline/adapters.py`. Any missing credential, dependency, or artifact fails
loudly for that video only; it never fakes success. The live pilot execution
(20-50 real TikToks) has **not** been run from CI; it is executed by a human or
an agent session with network access and `GEMINI_API_KEY` configured:

```bash
python -m tiktok_analytics_factory.pipeline run-pilot \
  --cohort config/pilot_cohort.json \
  --sources data/pilot_sources.csv \
  --output-root data/dataset \
  [--reviews data/manual_reviews.jsonl]
```

## Usage

```bash
python -m tiktok_analytics_factory.pipeline run-pilot \
  --cohort config/pilot_cohort.json \
  --sources data/pilot_sources.csv \
  --output-root data/dataset
```

- Source list must be an explicit CSV/JSONL (templates:
  `data/pilot_sources.template.csv`). Cohort template:
  `config/pilot_cohort.template.json`.
- Outputs: per-video record directories under `records/<video_id>/`,
  auditable `rejected_sources.jsonl`, `index.parquet`, and `pilot_report.json`
  containing all required metrics plus the gate decision.
- Resumable: reruns skip already-successful records; pass `--no-resume` to
  reprocess explicitly.
- Bounded retry: transient collection errors are retried up to
  `--retry-attempts` (default 3) with linear backoff; policy is logged and
  recorded in manifests.

## Review

`notebooks/02_pilot_review.ipynb` provides video playback, metadata,
shot timeline, CreativeIR/CanonicalIR summaries, provenance/cost, and a
per-video evaluation slot (`review.json`) — navigate videos via slider,
no code edits required.

## Gate

`ready-for-modeling-dataset` requires >=20 successes, >=85% success rate among
eligible attempts, 100% validation/projection on successes (derived from each
record's persisted `validation.json`/IR artifacts), manual review average
>=4.0/5 over at least max(5, ceil(20% of successes)) records, no reviewed
category with systematic severe errors (a category is blocked when reported in
more than half of the reviews, minimum 2 reports), measured costs/latency, and
isolated reproducible failures. Otherwise: `decompiler-needs-more-work`.

Current decision: **decompiler-needs-more-work** (the live 20-50 video pilot
has not been executed yet; the gate cannot pass without measured records).
