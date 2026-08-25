# Dataset QA, human review, and auditing

This document explains the QA layer that gates scale-up of collection. It
answers, for any record or dataset:

- Is this source in the approved cohort?
- Did every pipeline stage succeed?
- Does CreativeIR actually match the video?
- Is CanonicalIR consistent with CreativeIR?
- Are performance snapshots plausible and properly timestamped?
- What failed, and is the failure systematic?

## Dataset record layout

```text
data/dataset/<video_id>/
    record.json        # manifest: provenance, paths, versions, status
    perception.json    # deterministic media facts + shots
    creative_ir.json   # CreativeIR document
    canonical_ir.json  # CanonicalIR projection of CreativeIR
    performance.json   # Performance v0.1 snapshot(s)
```

The CanonicalIR projection rule lives in
`tiktok_analytics_factory.qa.projection.project_canonical`; the canonical
serialization rule is `records.canonical_json` (sorted keys, compact
separators). A stored CanonicalIR is consistent iff its `projection` payload
equals a fresh projection of the current CreativeIR under that serialization.

## Automatic validators

`python` module: `tiktok_analytics_factory.qa.validators`. Each validator
returns taxonomy-labelled issues; nothing raises on bad data. Registered
validators cover source/provenance, perception, CreativeIR, CanonicalIR, and
Performance. A future derived-target validator (#9) can be attached via
`register_target_validator(fn)` without changing QA itself.

Run them from Python:

```python
from tiktok_analytics_factory.qa.records import load_record
from tiktok_analytics_factory.qa.validators import run_validators

issues = run_validators(load_record("data/dataset", "<video_id>"))
```

## Error taxonomy

Versioned in `qa/taxonomy.py` (`TAXONOMY_VERSION`). Every human error carries
`category`, `severity` (`minor` | `material` | `blocking`), free-text `note`,
`timestamp`, and optional `shot_id` / `field` reference.

## Human review

Reviews persist as machine-readable JSON at:

```text
data/reviews/<video_id>/<review_id>.json
```

Each review stores reviewer name, timestamp, format + taxonomy versions, the
sha256 of the reviewed record manifest (`source_record_hash`), 1–5 scores for
the ten quality dimensions, errors, and notes. A note is mandatory when any
score <= 2 or any error severity is `blocking`; saving otherwise fails loudly.

### Review interface

```bash
pip install .[qa]
python -m tiktok_analytics_factory.qa review-app --dataset-root data/dataset --reviews-root data/reviews
```

(or `streamlit run` pointing at `src/tiktok_analytics_factory/qa/app.py`).

For one video it shows embedded playback, metadata/performance, the shot
timeline with representative frames, CreativeIR and CanonicalIR summaries,
version/provenance info, automatic validator results, cost/latency, and a
score/error form. Navigate with prev / next / random / dropdown. No code edits
required.

## Sampling helpers

`qa/sampling.py` provides deterministic sampling by seed, creator, pipeline or
model version, processing status, QA failure category, and performance-quantile
slices (e.g. bottom decile views), so manual QA is not biased toward easy or
high-performing videos.

## Dataset audit

```bash
python -m tiktok_analytics_factory.qa audit \
  --dataset-root data/dataset \
  --output data/reports/qa_report.json \
  [--reviews-root data/reviews]
```

No model or network calls. The report includes total records; status counts;
validation pass rate and issue counts per category; missing-metadata rates;
per-part schema validation rates; CanonicalIR projection mismatch count;
exact duplicate video IDs and source hashes; creator concentration;
pipeline/model/schema version distributions; cost/latency distributions; and
human review counts plus error counts/severity by category.

## Recommended workflow before approving scale-up

1. Run the audit command; investigate every `blocking` issue and any
   systematic category with a high count.
2. Sample records across creators/status/quantiles with a fixed seed.
3. Review each sampled record in the app; persist scores/errors.
4. Re-run the audit including reviews; require zero blocking errors and
   reviewed pass coverage across the sample before increasing collection.
