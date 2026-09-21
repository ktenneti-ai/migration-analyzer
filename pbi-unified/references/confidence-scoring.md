# Confidence Scoring (0–100)

Every measure in the conversion pipeline receives a numeric confidence score (0–100)
that governs how much human oversight the translation needs. Scores are the primary
system; bands, tiers, and A–F categories are derived labels.

## Bands

| Score | Band | Tier | Action |
|-------|------|------|--------|
| 90–100 | AUTO | T1 | Ship — mechanical translation, no human review needed |
| 70–89 | AUTO_SPOT_CHECK | T2 | Spot-check 1–2 result slices against the source |
| 40–69 | NEEDS_REVIEW | T3 | Candidate SQL emitted with `-- REVIEW` markers; human approves |
| 11–39 | MANUAL_PORT | T4 | Stub only — human writes the SQL |
| 0–10 | UNSUPPORTED | T4 | No Metric View equivalent (e.g. `USERNAME()` RLS) |

## Scoring Mechanics

### Starting Score
Every measure starts at 100 and is reduced by **deductions** (subtractive) or **caps**
(hard ceiling). Caps take effect after deductions — if the deducted score is already
below the cap, the cap has no effect.

### Deductions (subtractive from 100)

| Trigger | Deduction | Notes |
|---------|-----------|-------|
| Each Tier 2 function (IF, SWITCH, ISBLANK, iterators) | -12 each, max -36 | Pattern rewrite needed |
| CALCULATE with boolean filter | -15 | Boolean → WHERE clause |
| CALCULATE with FILTER() table arg | -25 | Complex filter table |
| KEEPFILTERS semantics | -20 | Unusual filter interaction |
| CALCULATE with unrecognized filter arg | -20 | Unknown complexity |
| VAR/RETURN usage | -10 | Needs inlining/decomposition |
| Iterator over virtual table | -35 | SUMX(FILTER(...)) → CTE/pre-agg |
| RANKX/TOPN | -30 | Window logic, usually consumer-side |
| LOOKUPVALUE | -25 | Needs new explicit join |
| BLANK vs 0/NULL sensitive comparison | -10 | Semantic difference risk |
| Uncataloged function (each) | -30 each, max -60 | Unknown translation path |

### Caps (hard ceiling)

| Trigger | Cap | Notes |
|---------|-----|-------|
| RLS functions (USERNAME etc.) | 10 | UNSUPPORTED in view |
| TREATAS/CROSSFILTER | 25 | Virtual relationship |
| USERELATIONSHIP | 30 | Rewires join graph per-measure |
| EARLIER/EARLIEST | 25 | Nested row context |
| Time intelligence functions | 35 | Always needs explicit date dim |
| Semi-additive functions | 35 | Snapshot/window pattern needed |
| ALL-family (total/window) | 55 | Not a plain aggregate |
| Bi-directional relationship | 45 | Filter path ambiguity |
| Many-to-many relationship | 45 | Bridge table complexity |

## Dependency Propagation

A measure can **never** score above its weakest dependency. If Measure B references
Measure A, and A scores 35 (MANUAL_PORT), then B's score is capped at 35 regardless of
B's own complexity.

Circular dependencies force all measures in the cycle to MANUAL_PORT (score 20).

## Parity Override

After parity testing (`reconcile.py --compare`):
- **All slices match**: score floors at 95 (AUTO/SPOT) or 80 (others)
- **Any slice mismatches**: score capped at 40 (NEEDS_REVIEW), MISMATCH flag set

Parity results are the strongest signal — they override the structural score in both directions.

## Model-Level Score

Weighted average of all measure scores (uniform weight unless `--usage` JSON provided).
Additional penalties:

| Penalty | Deduction |
|---------|-----------|
| Calculation groups present | -25 |
| RLS roles present | -5 |
| Bi-directional relationships (per group) | -10, max -30 |
| Many-to-many relationships (per group) | -10, max -30 |
| Inactive relationships present | -3 |
| Calculated tables present | -3 |

## A–F Category Derivation

Categories are derived from function patterns, not from scores:

| Priority | Condition | Category |
|----------|-----------|----------|
| 1 | RLS functions OR EARLIER OR score < 11 | F |
| 2 | Semi-additive functions | E |
| 3 | Time intelligence functions | C |
| 4 | CALCULATE filter args present | D |
| 5 | References other measures OR Tier 2 functions | B |
| 6 | Default | A |
