# Performance target specification (`performance_target_v0_1`)

Derived modeling targets built from immutable Performance v0.1 snapshots
(issue #3 layout). Raw snapshots are never modified; targets live in a
separate versioned artifact (e.g.
`data/pilot/performance_targets_v0_1.json`) validated by
`schemas/performance_target_v0_1.json`.

## Missing-data semantics

- `None` means unknown/unavailable. Zero never substitutes for unknown.
- A zero denominator yields a null ratio (`likes_per_view` etc.), not 0.
- Missing follower counts are **not** imputed as zero; in fact
  `follower_count` does not exist in `NormalizedMetadata`, so all
  creator normalization uses view-history baselines instead.
- A record whose inputs are insufficient is written with
  `is_valid=false` and explicit `invalid_reasons`
  (`missing_creator_identity`, `missing_views`,
  `insufficient_creator_history`, `missing_post_age_or_observation_time`).
  No value is fabricated.

## Candidate targets

| name | definition | role |
|---|---|---|
| `log_views` | `log1p(views)` | diagnostic baseline A only |
| `likes_per_view`, `comments_per_view`, `shares_per_view` | engagement / views | secondary descriptors B |
| `creator_relative_log_views` | `log1p(views) - median(log1p(views of the creator's OTHER videos))`, requiring ≥ `min_other_videos_for_creator_target` (=2) other valid videos | **primary target C** |
| `performance_residual` | `log1p(views) - expected_log_views`, where expectation comes from a transparent OLS fit `log1p(views) ~ intercept + log(post_age_days) + creator_baseline_log_views (+ missing indicator)` on strictly pre-creative/context variables | secondary target D |
| pairwise labels | within-creator pairs of `creator_relative_log_views`; `a_gt_b` if diff ≥ margin (0.25), `b_gt_a` if ≤ −margin, else `tie`; sampled with per-video cap, never O(n²) across the cohort | E |

## Creator baseline

Strict leave-one-out: the baseline median for a video is computed over the
creator's *other* videos only. The target video can never contribute to its
own baseline (enforced in `construct.creator_relative_log_views` and tested).
Creator identity is used for normalization but must later drive
creator-disjoint train/test splits (see `docs/target_leakage.md`).

## Snapshot-age policy

Preferred order per issue:

1. fixed-age repeated snapshots — infeasible on the pilot set (0 videos have
   more than one observation);
2. **explicit age adjustment** — implemented: the OLS residual target above;
3. narrow post-age window restriction — fallback if adjustment is impossible.

Records lacking `published_at` or observation time are marked invalid rather
than compared against age-adjusted peers without correction.

## Primary target selection

Selected: `creator_relative_log_views @ performance_target_v0_1`.

Criteria scores (see `docs/target_analysis_report.md`):

- coverage: highest among non-exposure-dependent candidates (80% pilot);
- robustness: median-based, immune to the 1.5M-view outlier;
- interpretability: log units relative to the creator's own typical video;
- stability: conclusions unchanged for `min_other_videos` ∈ {1,2,3};
- exposure independence: correlation with log(post age) ≈ 0 vs −0.054 raw;
- ranking suitability: directly supports within-creator pairwise labels.

Not selected because of correlation with any creative feature.

## Recomputation contract

Given the stored snapshot files and the artifact's `construction_config`
(hash-stable method version = sha256(config)[:12]), another engineer can
rerun:

```sh
python -m tiktok_analytics_factory.targets.build \
    data/pilot/snapshots out.json <cohort_id> <cohort_version>
python scripts/analyze_targets.py
```

and reproduce every target value deterministically from stored inputs,
without reading this document's prose.
