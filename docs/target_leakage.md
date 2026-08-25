# Target leakage rules

Rules governing which variables may touch target construction versus later
model features, for `performance_target_v0_1`.

## Permitted in target normalization

- Raw engagement counts from the observation-time snapshot (`views`,
  `likes`, `comments`, `shares`) — these define the label itself.
- Creator identity (`creator_id`/`creator_handle`) — used only to group
  videos for leave-one-out baselines.
- `published_at` / observation time — only for post age in the residual
  baseline.
- Creator view-history statistics computed **excluding** the target video.

## Permitted as model features at prediction time

- Creative content: caption text, hashtags, audio metadata, duration,
  video pixels/frames (CreativeIR/CanonicalIR).
- Context available before publication: creator handle/ID, posting time of
  day/day of week.

## Must never appear in both sides (trivial reconstruction)

- `views` (or `log_views`, or any monotone transform of it): it *is* the
  raw ingredient of every target. It must never be a ranker feature.
- Engagement ratios (`likes_per_view`, etc.): post-outcome observations;
  using them as features would leak outcome information into prediction.
- `creator_relative_log_views` / `creator_baseline_log_views` /
  `expected_log_views_age_model` / `performance_residual`: derived
  quantities that encode or invert the target; excluded from features.
- Post age at observation (`post_age_days`) is exposure, not creative
  quality; it is allowed only inside the normalization baseline, not as a
  ranker feature for quality claims.

## Creator baselines inside train folds

When training the future ranker, per-creator baseline statistics must be
recomputed **within each training fold only**, excluding both the target
row and all held-out rows. The cohort-level baselines stored in this v0.1
artifact are for analysis and pilot targets; fold-internal recomputation is
mandatory at modeling time so no validation/test row influences any
training baseline.

## Why creator-disjoint train/test splitting is required

Targets are normalized relative to creator history and pairwise labels are
sampled within creators. Splitting randomly by video lets a model exploit
creator-specific memorization (a held-out video's neighbors appear in
training), inflating evaluation scores without measuring creative quality.
Creator-disjoint splits force generalization to unseen accounts, which is
the actual product requirement.

## No future information

Nothing computed after the observation timestamp (later snapshot values,
subsequent performance, account growth) enters any target. Repeated
snapshots, when they exist, select one observation policy point; they never
blend future counts into an earlier label.
