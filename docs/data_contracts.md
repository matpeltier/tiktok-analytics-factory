# Data Contracts v0.1

Three versioned contracts ground all downstream pipelines. Later stages must
validate against these JSON Schemas (Draft 2020-12) instead of inventing ad-hoc
dictionaries. JSON Schema is the persisted contract; Python code only validates
against it.

| Contract | Schema | Example | Purpose |
|---|---|---|---|
| CreativeIR v0.1 | `schemas/creative_ir_v0_1.json` | `examples/creative_ir_v0_1_reference.json` | Full, auditable creative decompilation of one video |
| CanonicalIR v0.1 | `schemas/canonical_ir_v0_1.json` | `examples/canonical_ir_v0_1_reference.json` | Compact model-facing projection for analytics/ranking |
| Performance v0.1 | `schemas/performance_v0_1.json` | `examples/performance_v0_1_reference.json` | Raw platform metric snapshots |

## Global conventions

- **Timeline timestamps** are seconds (`float`) from the beginning of the media,
  never wall-clock offsets.
- **Unknown is not zero and not fabricated.** Unknown values are `null` or an
  explicit enum member such as `unknown` / `none_observed`, depending on field
  semantics (see below). `0` always means "observed zero".
- **Certainty** on transcribed text: `exact` = verbatim from deterministic
  evidence (OCR/ASR with high confidence); `uncertain` = model transcription.
- **Confidence** (inferred fields) is a closed enum: `high` / `medium` / `low`.
- Every record carries a `schema_version` and stable source identity
  (platform + video ID, plus source URL where appropriate).

## CreativeIR v0.1

Top-level blocks, deliberately separated:

| Block | Semantics |
|---|---|
| `source` | Normalized pointer to the ingested artifact. Does **not** duplicate the full raw metadata payload; carries caption/hashtags needed for analysis and an artifact hash or manifest reference. |
| `decompilation` | Provenance of this annotation: schema version, pipeline version, exact model ID, provider, prompt version, `created_at`, `annotation_mode` (`automated`/`manual`/`hybrid`). |
| `observed` | Claims grounded in source evidence: media summary, hook/narrative/marketing evidence, ordered `shots[]`. |
| `inferred` | Interpretation, never fact: concept, audience hypothesis, hook type/mechanism, narrative structure, attention/persuasion mechanisms, commercial interpretation. Rich fields carry `confidence` and optional rationale evidence refs. |
| `generation` | Optional; model-agnostic reconstruction instructions only. Vendor-specific fields (`higgsfield_prompt`, `veo_prompt`, Remotion component names) are forbidden by the schema. |

### Shots

Each shot has a stable ID (`shot-01`, `shot-02`, ...), start/end seconds,
subjects/actions with subject categories, visual description, framing scale,
camera movement (only when genuinely observable — otherwise `unknown`),
on-screen text and spoken dialogue each with `exact`/`uncertain` status, audio
observations with explicit uncertainty, entering transition, and `evidence`
references that distinguish `deterministic` facts (timecodes, OCR regions, ASR
spans) from `model` observations.

Shot-level visual/audio descriptions live **only** inside `observed.shots`;
there are no redundant top-level duplicates.

### Commercial vs non-commercial

`inferred.commercial_interpretation.status` is one of:

- `commercial` — product fields populated;
- `non_commercial` — product/CTA fields must be `null`; no invented product data;
- `uncertain` — status unclear; product fields may be null.

Commercial content can express product presence, first product appearance
(seconds), problem/desire, promise/claim, proof type, trust signals, objections
addressed, offer, CTA text/type. The reference TikTok (#2 sourdough video) is
**non-commercial**; the synthetic commercial branch is exercised by a test
fixture (`SYNTHETIC_COMMERCIAL_CREATIVE` in `tests/test_contracts.py`) rather
than by pretending the reference video is commercial.

## CanonicalIR v0.1

Compact projection consumed by analytics/ranking. Contains only controlled
enums, booleans, counts, timing and numeric fields, plus minimal labels where
controlled vocabulary would destroy information (mechanism labels).

Deliberately excluded:

- the entire `generation` block and any reconstruction prose (schema rejects
  additional properties, so `generation` cannot appear);
- any raw performance values (`views`, `likes`, ...) — schema rejects them;
  performance lives exclusively in Performance v0.1 records joined by video ID;
- long free-text from CreativeIR — dropped, never serialized into an `extra`
  blob.

Field set: duration, shot count and shot-duration distribution, subject
categories, on-screen text presence/role, spoken dialogue presence, camera-motion
categories, transition categories, audio categories, hook timing/type,
narrative structure, attention/persuasion mechanism labels, proof type,
trust-signal and objection counts, CTA type, commercial status, overall
confidence. A ranker should need nothing else from CreativeIR prose.

## CreativeIR → CanonicalIR projection

Implemented in `tiktok_analytics_factory.contracts.projection`.

- Pure function: same validated CreativeIR input always yields identical output.
- No model calls.
- Input must validate against the CreativeIR schema; invalid shots (end <=
  start, out-of-order starts) raise `ProjectionError`. Failures are loud.
- Output is itself validated against CanonicalIR v0.1 before being returned.
- Fields absent from CanonicalIR are intentionally dropped (not accumulated).
- `projected_at` is the single caller-supplied timestamp; everything else derives
  deterministically from the CreativeIR payload.

Projection conventions worth knowing:
- `subject_categories`, `camera_motion_categories`, `transition_categories`,
  `audio_categories`: unique categories encountered across shots, in encounter
  order; `unknown`/`none` values dropped.
- `on_screen_text_role`: `cta` if any overlay matches CTA keywords, else
  `hook_text` if an `exact` overlay appears within the first 3 s, else
  `caption_subtitle` if any overlay exists, else `none_observed`.
- `trust_signal_count` / `objection_count`: counts derived from the commercial
  interpretation lists (0 for non-commercial).

## Performance v0.1

One record = one raw observation snapshot of one video at one instant.

- Metrics (`views`, `likes`, `comments`, `shares`, optional `saves`,
  `follower_count_at_observation`) are nullable integers >= 0.
  **`null` = unknown/unavailable; `0` = observed zero. Never conflate them.**
- Multiple observations of the same video are separate immutable records keyed
  by `observed_at`; old snapshots are never mutated.
- `published_at` / `observed_at` are required ISO-8601 UTC timestamps;
  `age_since_publish_seconds` may be stored directly (and may be null when
  either endpoint is unknown).
- `provenance` records collector name/version, source URL, and a reference to
  the immutable raw payload backing the snapshot for auditability.
- Forbidden by design: virality scores, residuals, normalized labels, ranker
  outputs. Those belong to later issues.

## Which object do I use?

- **Modeling/ranking features:** CanonicalIR only. Do not parse Gemini
  reconstruction prose, and never mix raw performance into creative features —
  join Performance snapshots separately by video ID when training targets exist.
- **Inspection, audit, decompilation quality review, reconstruction briefs:**
  CreativeIR (its `generation` block must never leak into modeling inputs).
- **Any engagement number:** Performance v0.1 snapshots only.
