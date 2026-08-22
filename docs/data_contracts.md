# Data Contracts v0.1

Three versioned JSON Schema (Draft 2020-12) contracts govern all downstream
pipelines. The schemas under `schemas/` are the persisted contracts; the
Python helpers in `src/tiktok_analytics_factory/contracts/` only validate and
project against them.

| Contract | Schema | Purpose |
|---|---|---|
| CreativeIR v0.1 | `schemas/creative_ir_v0_1.json` | Rich, auditable creative decompilation of one video |
| CanonicalIR v0.1 | `schemas/canonical_ir_v0_1.json` | Compact model-facing projection for analytics/ranking |
| Performance v0.1 | `schemas/performance_v0_1.json` | Raw observed platform metric snapshots |

Reference examples live in `examples/*_reference.json`. They are grounded in
the real issue #2 reference video, TikTok
[`6718335390845095173`](https://www.tiktok.com/@scout2015/video/6718335390845095173)
by `@scout2015` (published 2019-07-27T13:32:38Z). The raw collector payload
backing every factual value is preserved at
`examples/artifacts/metadata_6718335390845095173.raw.json`.

**Grounding rules for the reference examples (enforced by tests):**

- Only deterministic metadata facts are asserted: video ID, source URL,
  creator handle/ID, caption/hashtags, duration, published_at, and the public
  metric counters present in the raw payload (`view_count`, `like_count`,
  `comment_count`, `save_count`).
- Media frames and audio were **not inspected** when the CreativeIR example was
  authored, so all visual/audio observations are `null`, `[]`, or
  `"unknown"`; nothing about shots, text, dialogue, or music is invented.
- `shares` in Performance is `null`: the payload exposes `repost_count=1465`,
  but a repost→share mapping is unverified, so it is not asserted.
- `follower_count_at_observation` is `null` (absent from the payload).
- The CreativeIR example omits the optional `generation` block because no
  reconstruction instructions can be grounded without media inspection.
- `decompilation` uses `annotation_mode: "manual"` with
  `model_id`/`provider`/`prompt_version` set to the documented literal
  `"none"`, meaning no model produced any claim in this record.
- Commercial status is `"uncertain"` (details `null`) since commerciality
  cannot be verified without inspecting the media. The commercial branch of
  CreativeIR is exercised by a clearly-synthetic fixture in
  `tests/test_contracts.py::test_synthetic_commercial_branch_projects`; we do
  not pretend the reference video is commercial.
- Regression tests ban the previously fabricated identifiers
  `@bakerylab` / `7300000000000000001` from all reference examples and docs.

### Grounding provenance

The reference examples were regenerated on the delivery VPS from a live
ingestion run of `https://www.tiktok.com/@scout2015/video/6718335390845095173`
into `data/raw/` (not copied from a prior artifact):

- Collector: `yt-dlp 2026.8.19`; `pyktok` was attempted first and failed
  (`collector_dependency_unavailable`); the fallback is traced in
  `data/raw/6718335390845095173/manifest.json` (`attempted_collectors_in_order`,
  per-collector `attempts[]`).
- The creative example's `source.artifact_sha256` is the real media SHA-256
  from that manifest; regression tests
  (`test_examples_match_live_ingestion_artifacts`,
  `test_committed_audit_copy_matches_live_payload`) verify examples against
  the live artifacts whenever they are present and skip otherwise.
- Every value unavailable from the payload remains `null`/`unknown`/
  `"uncertain"` (e.g. `shares`, follower count, all media-frame observations).

## Global conventions

- **Versioning.** Every object carries `schema: {name, version}` with a
  literal version (`"0.1"`). Breaking changes require a new file
  (`*_v0_2.json`), never an edit in place.
- **Timeline units.** All timeline timestamps (`start_seconds`,
  `end_seconds`, hook timing, payoff timing, etc.) are **seconds from the
  beginning of the media**.
- **Unknown is never fabricated certainty.**
  - Nullable fields: JSON `null` means *unknown / not derivable*. It never
    means zero.
  - Closed enums that need an "we cannot tell" value use the explicit string
    `unknown` (e.g. `framing`, `camera_movement`, `hook_type.value`).
  - Audio observations carry per-channel certainty:
    `observed | uncertain | absent | unknown`.
  - Text transcription carries an `exact: boolean`: verbatim vs approximate.
  - Inferred fields carry `confidence: high | medium | low` plus optional
    `rationale`.

## CreativeIR v0.1

Top-level blocks are mandatory and semantically separated:

- **`source`** — normalized pointer to the ingested video (platform, video
  ID, source URL, creator handle when known, caption/hashtags, duration,
  published_at, artifact hash, manifest reference). It deliberately does not
  duplicate the full raw metadata payload; the manifest carries that.
- **`decompilation`** — provenance of the run that produced this object:
  pipeline version, exact model ID, provider, prompt version, `created_at`,
  and `annotation_mode` (`automated | manual | hybrid`).
- **`observed`** — claims grounded in source evidence only. Video-level
  summary, hook evidence, narrative evidence, marketing evidence, first
  product appearance timing, and ordered `shots[]`. Every shot has a stable
  ID (`shot_NNN`), start/end seconds, subjects/actions, visual description,
  framing, camera movement, on-screen text, spoken dialogue, audio
  observations with certainty, transition-in, and `evidence[]` entries whose
  `kind` distinguishes `deterministic` facts from `model_observation`
  claims.
- **`inferred`** — interpretation, never fact. Concept, audience hypothesis,
  hook type/mechanism, narrative structure, attention mechanisms, persuasion
  mechanisms, and `commercial`. Interpretive fields wrap their value with
  `confidence` and optional rationale/evidence refs.
- **`generation`** — allowed **only** here: model-agnostic reconstruction
  instructions (global brief, per-shot reconstruction intent keyed by
  `shot_id`, pacing, text treatment, transitions, continuity constraints,
  payoff timing). Vendor-specific syntax (`higgsfield_prompt`, `veo_prompt`,
  Remotion component names) is forbidden by design.

### Commercial analysis and `not_applicable`

`inferred.commercial.status` is one of:

- `commercial` — `details` is **required** and contains product presence,
  first product appearance seconds, problem/desire, promise/claim, proof
  type, trust signals, objections addressed, offer mechanics, and CTA
  (literal text + `text_exact` + closed-type enum).
- `non_commercial` — `details` must be `null`. This is the explicit
  `not_applicable` mechanism: no product/CTA fields are invented.
- `uncertain` — `details` may be `null` or partially filled with
  low-confidence labels.

The schema enforces the non_commercial → `null details` rule via `if/then`.

## CanonicalIR v0.1

A compact projection consumed by feature extraction/ranking. Properties:

- Contains only controlled enums, booleans, counts, timing numbers, label
  lists, and minimal provenance (`decompilation_ref`). Free prose is gone;
  the only preserved "stable text" is label strings copied from inferred
  mechanism lists.
- `additionalProperties: false` at every level means a `generation` block or
  any raw performance payload **cannot validate**.
- Nullability semantics for features: `null` = unknown/not determinable;
  `false` = explicitly observed as absent. Example: `music_present: true`
  means music was observed somewhere; `false` means every shot's audio was
  marked `absent`; `null` covers uncertain/unknown mixes.
- `cta_type` uses `"not_applicable"` for non-commercial videos and `null`
  for uncertain/commercial-without-CTA.
- Raw performance values are structurally excluded; join to Performance
  records via `source.video_id` only.

## CreativeIR → CanonicalIR projection

Implemented in
`tiktok_analytics_factory.contracts.project_creative_to_canonical`:

- Pure function; same input → same output; **no model calls**.
- Input must be valid CreativeIR v0.1 (schema + semantic checks); invalid
  input raises `ContractValidationError` loudly.
- Output is re-validated against CanonicalIR before returning.
- Fields not representable in CanonicalIR are dropped entirely — there is no
  `extra` blob.
- Deterministic rules (documented, testable):
  - `subject_categories`: keyword classification of shot subjects
    (person_creator / food / environment / product), order-preserving,
    deduplicated; `none_visible` when no shot lists subjects.
  - `visible_text_roles`: `promotional` if text matches promo keywords
    (link/shop/buy/%/off/code/bio), else `instructional`.
  - `camera_motion_categories` / `transition_categories`: unique values in
    order of appearance, skipping `unknown`.
  - `music_present` / `sfx_present`: tri-state collapse over per-shot
    certainty values (`any observed → true`; `all absent → false`;
    otherwise `null`).
  - Duration stats computed directly from shot boundaries; mean is a plain
    arithmetic mean.
  - Mechanism label lists are sorted for stable output.
- The committed example `examples/canonical_ir_v0_1_reference.json` must be
  byte-for-byte reproducible via the projection from the committed Creative
  reference (enforced by `test_projection_matches_committed_reference_example`).

## Performance v0.1

Raw platform-metric snapshots only. One record = one observation moment.

- Required identity: platform, video_id, observed_at, collector provenance
  (name, collected_at, method, raw_payload_reference).
- `published_at` nullable; `age_since_publish_seconds` derived and
  cross-checked against both timestamps (±1s tolerance) by the semantic
  validator; null when published_at is null.
- Metrics are nullable integers ≥ 0. **`0` means observed zero; `null` means
  unknown/not exposed.** `saves` included only when truly available.
- `follower_count_at_observation` recorded only if publicly available at the
  observation time.
- Snapshots are append-only: multiple observations of the same video are
  separate records with distinct `observed_at`; old snapshots are never
  mutated.
- Forbidden by schema (`additionalProperties: false`) and by policy:
  `virality_score`, residuals, normalized labels, ranker outputs. Those
  belong to later normalization issues and reference this contract by
  `(video_id, observed_at)`.

## Which object do I use?

- **Inspecting/auditing decompilation quality or driving generation** →
  CreativeIR v0.1.
- **Feature extraction, dataset building, ranking models** → CanonicalIR
  v0.1 only. Never train on CreativeIR prose, never use `generation`.
- **Any performance modeling** → join CanonicalIR features with Performance
  v0.1 snapshots by `video_id`; normalization/residual labels come later and
  must not be written back into either v0.1 contract.
