# Architecture

This document defines the non-negotiable product contracts of the TikTok Analytics
Factory. Every implementation issue must respect them.

## Product boundary

The long-term system:

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

The legacy repository `matpeltier/tiktok-factory` is **reference-only** (product
learnings). Its code, history, runtime state, and test artifacts must never be merged
into this repository.

## Invariants

### 1. Raw source data is immutable

For every collected TikTok, preserve the original downloaded video and raw public
metadata. Derived artifacts may be regenerated; raw source artifacts must never be
silently overwritten.

### 2. Creative description and performance are separate

- **CreativeIR**: rich, auditable description of what a video is and how it works
  creatively.
- **CanonicalIR**: compact model-facing projection for analytics/ranking.
- **Performance**: public performance observations and later normalized/derived
  targets.

A model must never infer that a creative property exists merely because a video
performed well.

### 3. Observed / inferred / generation are separate

Creative annotations distinguish:

- `observed`: visible/audible/source-metadata facts;
- `inferred`: creative, narrative, audience, commercial, or persuasion interpretation;
- `generation`: instructions for reproducing or creating a creative.

Do not mix model interpretation into observed facts.

### 4. Every derived artifact is versioned

Every processed record is traceable to:

- source identifier;
- schema version;
- pipeline version;
- prompt version;
- model/provider exact ID;
- processing timestamp;
- code revision where practical.

### 5. One micro-niche first

All dataset experiments stay inside one precisely defined micro-niche until an explicit
roadmap issue changes this. Agents must not broaden to multiple sports/categories/
verticals for convenience.

### 6. Small experiment before scale

Required progression:

`1 reference video -> validated decompiler -> 20–50 video pilot -> modeling dataset ->
ranker -> generation experiment -> live feedback loop`.

Do not jump directly to thousands of videos, model fine-tuning, cloud queues, or
automated publishing.

### 7. Deterministic facts beat model guesses

Facts that can be derived deterministically (duration, resolution, fps, codec, file
size, detected cut timestamps, etc.) come from deterministic tooling rather than a VLM
guess.

### 8. Preserve raw model responses

Never save only the parsed/cleaned response from Gemini or another model. Raw output
and parsed/validated output must both be recoverable for audits and reprocessing.

### 9. Fail loudly

No silent fallback. Every fallback collector/model/tool path is recorded in
provenance. Per-video failures are explicit and must not corrupt successful records.

### 10. Do not build infrastructure without an observed requirement

No LangGraph, queue, Kubernetes, distributed workers, complex databases, autonomous
agent orchestration, or large production platform until a later issue demonstrates a
concrete need.

## Runtime baseline

- Python 3.11+
- Single `pyproject.toml` as project/dependency configuration source of truth
- Tests via `pytest`
- Lightweight standard lint/format tooling only; no heavy frameworks
- Secrets via environment variables or a git-ignored local `.env`; credentials are
  never committed
