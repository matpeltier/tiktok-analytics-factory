# Multi-step CreativeIR decompiler (two-pass)

Architecture:

```text
MP4
  -> deterministic perception (#5, precomputed artifacts)
  -> Pass A  Gemini factual shot analysis   (prompts/multistep_pass_a_shot_analysis_v0_1.txt)
  -> Pass B  Gemini global creative synthesis (prompts/multistep_pass_b_synthesis_v0_1.txt)
  -> deterministic provenance merge (src/.../multistep/merge.py)
  -> CreativeIR v0.1 schema validation + CanonicalIR projection (contracts)
  -> side-by-side evaluation vs the #4 single-pass baseline
```

Exactly two model calls per run by default; a third pass is not implemented.
No OCR/transcription/audio specialists are used.

## Running

```bash
export GEMINI_API_KEY=...
PYTHONPATH=src MULTISTEP_MODEL_ID=<model-id> \
  python -m tiktok_analytics_factory.multistep --video-id 6718335390845095173
```

Artifacts land in
`data/derived/<video_id>/decompilation/multi_step/<run_id>/` exactly as
specified in the issue (raw requests/responses for both passes are preserved,
never overwritten).

## Invariants

- Shot boundaries and media facts always come from the #5 perception outputs;
  model payloads that attempt to restate/alter them raise `MergeError`.
- Evidence refs distinguish `deterministic` vs `model_observation`.
- Schema failure or canonical-projection failure fails the run loudly and is
  never persisted as a success (`validation.json` records the failing stage).
- The same 11-category rubric (#4) scores both pipelines;
  `evaluation.py::evaluate_decision` applies the issue's quality gates and
  emits exactly one of `validated-for-pilot` / `needs-one-video-fix`.

## Decision gate status

The reference-video run was executed for real against Gemini
(`gemini-3.6-flash`, two calls: pass A 14,127 in / 2,172 out tokens; pass B
20,406 in / 1,437 out tokens). Artifacts:
`data/derived/6718335390845095173/decompilation/multi_step/20260822T224249Z_341b6da2/`
(git-ignored; raw responses preserved in place).

- CreativeIR v0.1 schema validation: **pass**; CanonicalIR projection: **pass**.
- Deterministic duration/resolution/fps/codec exactly equal to #5 outputs;
  shot boundaries identical to the #5/manual hard-cut annotation.
- Manual rubric (same 11-category rubric as #4, scored against the committed
  reference annotations and frame-by-frame review evidence):
  multi-step average **4.545** vs baseline **3.818**; no category below 4;
  unsupported claims 2 vs baseline 3.
- Operational: total latency 42.584 s, total cost $0.078866 (pricing
  $1.5/$7.5 per Mtok input/output, same basis as the #4 baseline), 2 model
  calls.

All 11 decision gates passed. Recorded decision:

validated-for-pilot

Known residual weaknesses recorded in `evaluation.json`: one accessory
mislabel ("pink vest" vs collar) and emotional-state wording ("happy",
"smiling") embedded in observed shot descriptions; whip-pan blur character of
the ~3.4s transition described only as "cut". None block the gate; the pilot
issue may proceed.
