# Roadmap

Issue-driven roadmap. Detailed requirements live in the GitHub issues; this file only
summarizes the progression.

## Stage 0 — Bootstrap (current)

Clean repository skeleton, project contracts, and invariants (`docs/architecture.md`).
No product functionality yet.

## Stage 1 — Single-video foundation

Define the micro-niche precisely. Ingest one reference video: deterministic media
facts, raw metadata capture, and the first CreativeIR schema with
observed/inferred/generation separation.

## Stage 2 — Validated decompiler

Creative decompilation pipeline for single videos with full provenance and preserved
raw model responses, validated against schemas.

## Stage 3 — Pilot corpus

20–50 video pilot within the micro-niche. Immutable raw storage, per-video failure
isolation, dataset assembly with Performance kept separate from creative description.

## Stage 4 — Dataset & CanonicalIR

Modeling dataset built from pilot learnings; CanonicalIR projection defined and
versioned.

## Stage 5 — Ranker

Analytics/ranking over the dataset to surface winning creative mechanisms.

## Stage 6 — Generation experiment

Candidate CreativeIRs converted to generation instructions; small-scale rendering and
controlled publishing experiments.

## Stage 7 — Feedback loop

Performance feedback flows back into the dataset, closing the loop.

Infrastructure (queues, orchestration, databases beyond files) is added only when a
concrete issue demonstrates the need.
