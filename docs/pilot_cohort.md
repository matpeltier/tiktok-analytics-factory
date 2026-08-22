# Pilot cohort: micro-niche selection and cohort contract

Status: **DRAFT — PENDING PROJECT-OWNER APPROVAL.**

Per the issue's human-decision rule, the final niche must be explicitly approved
by the project owner before this issue is closed. The interactive approval tool
(`dk_ask_human`) was **not available** during implementation, so this document
records the candidate comparison and the full proposed contract, but the niche
is **not finalized** here. `config/pilot_cohort.json` is marked
`approval_status: "pending_owner_approval"` and downstream agents must treat it
as provisional until the owner approves exactly one candidate.

---

## 1. Candidate micro-niche comparison

All candidates live inside the intended broader area: **sport / affiliate-friendly
short-form content on TikTok**.

### Candidate A — Single-exercise form tutorials (`single_exercise_form_tutorial`)

| Criterion | Assessment |
|---|---|
| Plain-language definition | A short video where one creator demonstrates **one specific gym exercise**, explaining setup, execution cues, and common mistakes. No workout program, no vlog, no product pitch as the primary content. |
| Strategic interest | Directly aligned with the factory's goal of decompiling *creative mechanisms*: these videos have a repeatable archetype (hook → demo → cue → mistake → CTA) whose variation plausibly drives performance differences within a homogeneous audience intent ("how do I do X"). |
| Affiliate/commercial prevalence | Common: creators frequently link programs, equipment, supplements in bio/links. Enough to study commercial variants without requiring them. |
| Public example availability | Very high; thousands of videos under #exercisetutorial, #formcheck, #gymtips, per-exercise hashtags (#deadlift, #hipthrust...). |
| Creator diversity | High: many mid-size fitness creators (10k–1M followers) plus large accounts. Not dominated by a handful of celebrities at pilot scale. |
| Typical length/format | 15–60 s vertical video, single-location gym setting, voiceover or on-screen text cues. Highly uniform format → fewer confounders. |
| Performance metadata observable | Yes: public views/likes/comments/shares/saves via existing ingestion collectors. |
| Confounders | Creator follower count (handled via performance snapshot policy); music/trend audio; occasional thirst-trap drift (excluded by rule). |
| Legal/collection friction | Low: public videos, standard public-metadata collection already implemented. No sports-rights issues. |
| Scale feasibility (300–1500) | Easily reachable within the narrower sub-definition. |

### Candidate B — Running shoe & gear first-impression reviews (`running_gear_first_impression`)

| Criterion | Assessment |
|---|---|
| Definition | One creator gives a first impression / mini-review of **one specific running product** (shoe, watch, insole) after real use, 15–60 s. |
| Strategic interest | Strongest affiliate/commercial signal; directly monetizable learnings. |
| Affiliate prevalence | Very high — this is inherently commerce content. |
| Availability | High (#runningshoes, #runtok), though somewhat smaller than Candidate A. |
| Creator diversity | Medium: skewed toward run-creators with brand relationships. |
| Format | Talking-head + b-roll of product; more variable structure than A. |
| Performance observable | Yes. |
| Confounders | Brand halo effects (Nike vs unknown brand) can dominate creative quality; sponsored vs organic mix harder to separate. |
| Legal friction | Low–medium: brand names in dataset artifacts; no scraping restrictions beyond TikTok ToS. |
| Scale feasibility | Likely sufficient but thinner than A. |

### Candidate C — Sports highlight commentary/reaction (`sports_highlight_reaction`)

| Criterion | Assessment |
|---|---|
| Definition | Creator reacts to or commentates a professional sports highlight clip. |
| Strategic interest | High reach potential. |
| Affiliate prevalence | Low (mostly betting promos — legally sensitive). |
| Availability | High volume. |
| Creator diversity | High. |
| Format | Highly variable (reaction face-cam, green-screen, edited breakdowns). |
| Performance observable | Yes. |
| Confounders | Severe: underlying match interest dominates performance; embedded rights-held footage creates copyright takedown risk and unstable corpora (videos disappear). |
| Legal friction | **High**: redistribution of league footage; takedowns would corrupt a longitudinal dataset. |
| Scale feasibility | Volume fine, corpus stability poor. |

### Recommendation

**Candidate A (`single_exercise_form_tutorial`)** is the recommended niche:
most homogeneous format, largest public availability, lowest legal friction,
enough commercial content to study affiliate variants later, and its creative
structure maps cleanly onto CreativeIR decompilation. Candidates B and C remain
documented as future-cohort options.

> ⚠️ This recommendation requires explicit owner approval. If approved, flip
> `approval_status` in `config/pilot_cohort.json`, set `approved_by` /
> `approved_at`, and record it in git history referencing this issue.

---

## 2. Cohort contract (proposed, pending approval)

### Identity

| Field | Value |
|---|---|
| `cohort_id` | `pilot-v1-single-exercise-form-tutorial` |
| Name | Single-exercise form tutorials |
| Platform | TikTok only |

### Inclusion rules (all must hold)

1. Video is publicly accessible on TikTok.
2. Primary content is demonstrating/explaining **exactly one** resistance or
   bodyweight exercise (setup, execution, cues, or mistakes). Multi-exercise
   routines, full workouts, program pitches, and pure motivation/talking-head
   videos are out.
3. Format: single-creator vertical video ≤ 90 s, shot primarily in a gym/home-gym
   or equivalent training context.
4. Language: English spoken, captioned, or text-overlaid (any accent/dialect;
   non-English with English subtitles also accepted).
5. Creator account's primary content theme is fitness/strength training
   (spot-check their recent grid); accounts that are clearly comedy/aggregation/
   compilation pages are excluded.
6. Minimum metadata present: TikTok video ID, source URL, creator handle,
   duration, and at least one engagement metric (views) observed at collection
   time.

### Exclusion rules (any one excludes)

1. Content is primarily selling a specific branded product in-video (supplement
   tub close-ups, discount codes read aloud) — commercial policy is `allowed`
   via bio links only, not in-video hard-sell.
2. Music/performance content, dance trends, memes using an exercise as backdrop.
3. Sexualized/thirst-trap framing where exercise demonstration is secondary.
4. Medical/rehab claims ("fix your back pain", injury treatment advice).
5. Compilation/reaction videos of other creators' clips.
6. Videos under 10 s or over 90 s.
7. Known re-uploads of another creator's video (see duplicates below).

### Geographic constraints

None beyond language: any country of origin, English-language content.

### Publication-date window

Pilot sampling window: videos published within the **12 months preceding pilot
collection start**. Record exact window dates when sampling begins. No
minimum age; very recent (< 14 days) videos are flagged `immature_observation`
since engagement has not stabilized.

### Commercial-content policy

`allowed_flagged`: affiliate/bio-link commerciality is permitted and must be
flagged per source (`commercial_flag: none | bio_link_only | in_video_soft`,
where `in_video_soft` = mentions own program/app without hard product sell).
Hard-sell in-video content is excluded per rule E1.

### Duplicate / repost policy

- The same TikTok video ID is always one source record (enforced by ingestion idempotency).
- Obvious direct reposts/copies of another creator's video are excluded from the
  pilot cohort (they are not independent creative examples) and recorded in a
  `duplicate_of` note rather than silently dropped.
- Near-duplicate detection is **manual** during the pilot: the sampler records
  suspected near-duplicates (same exercise + substantially identical script/shot
  list) in the source notes; keep only the earliest-published instance.

### Performance observation policy

For every ingested source, store:

- `published_at` when available (normalized metadata field);
- `observed_at` timestamp for every performance snapshot (ingestion already
  appends timestamped snapshots);
- creator handle and creator ID when available;
- follower count when available;
- raw `views`, `likes`, `comments`, `shares`, `saves` — never normalized at
  ingestion time. Normalization/targets are defined by a later issue.

### Sampling policy (pilot, 20–50 videos)

Non-cherry-picked, performance-stratified manual sample:

1. Build a candidate pool by browsing the niche hashtags above; log every
   considered URL (accepted or rejected with reason) so the process is auditable.
2. Stratify the final 20–50 into roughly equal thirds by observed views at
   collection time relative to what is typical in the pool:
   - low (~bottom third), medium, high (~top third).
3. Cap any single creator at **3 videos** to preserve creator diversity.
4. Do not select only viral winners; the negative/comparison population is
   mandatory for later extraction-quality and modeling work.
5. Sample manually/publicly (no bulk scraping).

### What would force a future cohort version bump

- Changing niche definition (new cohort, not a version bump of this one).
- Broadening/narrowing inclusion rules materially (e.g., allowing multi-exercise
  content, changing language policy).
- Changing duplicate policy from exclude-reposts to include-flagged.
- Changing platform or adding a second platform.
- Any change that makes previously-ingested sources ineligible ⇒ new
  `cohort_id`; eligibility changes must never retroactively mutate existing
  datasets' membership.
