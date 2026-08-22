# TikTok Analytics Factory

A clean-room repository for building a TikTok creative analytics and generation system:
collect videos from one micro-niche, decompile them into structured creative
representations, build datasets, rank winning creative mechanisms, and eventually
generate and test new creatives in a controlled feedback loop.

> **Clean-room rule:** this repository replaces `matpeltier/tiktok-factory` as the
> product source of truth. The old repo may be consulted for *product learnings only*
> and must never be copied wholesale (code, history, runtime state, or test artifacts).

## The long-term loop

```text
TikTok sources
  -> ingestion
  -> creative decompilation
  -> CreativeIR / CanonicalIR + Performance
  -> dataset
  -> analytics / ranker
  -> winning creative mechanisms
  -> candidate CreativeIRs
  -> rendering / generation
  -> controlled publishing experiment
  -> performance feedback
  -> dataset update
```

## Current stage

**Stage 0 — bootstrap.** This repository currently contains only project contracts,
structure, and documentation. No collector, decompiler, dataset pipeline, ranker,
dashboard, or generation system exists yet. See `docs/roadmap.md`.

## Core concepts

The system preserves three distinct concepts — never merged:

- **CreativeIR** — rich, auditable description of what a video *is* and how it works
  creatively. Distinguishes `observed` facts, `inferred` interpretation, and
  `generation` instructions.
- **CanonicalIR** — compact model-facing projection of CreativeIR for
  analytics/ranking.
- **Performance** — public performance observations and later normalized/derived
  targets.

A model must never infer that a creative property exists merely because a video
performed well.

## Getting started

Requires Python 3.11+.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Secrets are supplied via environment variables or a local `.env` file (git-ignored).
Never commit credentials.

## Repository layout

```text
docs/       architecture contracts and roadmap
src/        package source code
schemas/    versioned data schemas (future)
examples/   small illustrative examples (future)
notebooks/  exploratory analysis (future)
tests/      pytest suite
data/       local artifact layout documentation; raw media is git-ignored
```
