# Review Rubric

Automated and manual checks for the review step (Step 7). The `review.py` script handles
mechanical checks; the assistant adds C-level re-derivation and judgment findings.

## Review Posture

Assume the converter is wrong until evidence says otherwise. Specifically hunt the
silent-wrong-number classes: fanout joins, BLANK/NULL drift, dropped CALCULATE filters,
auto-ported time intelligence, type coercion in CASE branches, decimal→double currency sums.

## Automated Checks (review.py)

### A-level: Structural Validation

| Check | Severity | What |
|-------|----------|------|
| A1 | CRITICAL | YAML parses; required keys (version, source, measures) present; version is 1.1 |
| A2 | MEDIUM | Active model.json relationships covered by spec joins (new: automated) |
| A4 | HIGH | No function/cast in join predicates (fix key types upstream) |
| A5 | CRITICAL/HIGH | Grain checks generated and available for execution |
| A6 | MEDIUM | No duplicate dimension or measure names |
| A8 | HIGH | Metric View syntax verified against current Databricks docs (gate G6) |
| A9 | CRITICAL | profile.json present; all PBI tables matched; catalog scan verified |

### B-level: Measure Quality

| Check | Severity | What |
|-------|----------|------|
| B1 | HIGH | Every measure has `-- DAX:` provenance comment (gate G2) |
| B2 | CRITICAL | No window functions or subqueries inside measure expr (gate G7) |
| B3 | HIGH | No bare division without try_divide guard |
| B5 | HIGH | CALCULATE in DAX but no FILTER/WHERE in SQL — dropped filter? (new: automated) |
| B9 | CRITICAL | No unreviewed markers (`-- REVIEW`, `-- CANDIDATE`, `-- TODO`) shipped |
| B10 | HIGH | No unresolved `[MeasureRef]` in spec — inline or use MEASURE() (new: automated) |
| B11 | CRITICAL | varchar_numeric columns feeding measures have try_cast wrapper |

### C-level: Manual Findings (assistant adds)

| Check | Severity | What |
|-------|----------|------|
| C1 | varies | Re-derive SQL from original_dax for NEEDS_REVIEW+ measures; disagreements become findings |
| C2 | CRITICAL | Parity MISMATCH — triage root cause (fanout/blank/dropped filter/date grain/type) |
| C4 | HIGH | Model-coverage BLOCKER/HIGH items undecided (gate G5) |

### D-level: Optimization (after correctness)

| Check | Severity | What |
|-------|----------|------|
| D1 | LOW | Casts in join predicates → fix key types upstream |
| D2 | LOW | Wide dimension sources → column pruning |
| D3 | MEDIUM | Iterator measures → point at pre-aggregated table |
| D4 | MEDIUM | Missing date-dim period columns for time intelligence |
| D5 | LOW | Ratio-of-total measures → consumer-side MEASURE() pattern |
| D6 | LOW | Duplicate subexpressions → shared helper measure |
| D7 | LOW | Liquid clustering recommendation for fact table |
| D8 | LOW | Genie natural-language grounding surface (comments, synonyms) |

## Severity Weights (for review score)

| Severity | Weight |
|----------|--------|
| CRITICAL | 25 |
| HIGH | 10 |
| MEDIUM | 4 |
| LOW | 1 |

Review score = 100 - sum(severity weights of all findings).

## Verdict

| Condition | Verdict |
|-----------|---------|
| Score ≥ 90 AND no CRITICAL findings | APPROVE |
| Score ≥ 70 AND no CRITICAL findings | APPROVE_WITH_CONDITIONS |
| Otherwise | REJECT |

## Acceptance Gates (G1–G8)

Verdict = REJECT if any gate fails (unless user explicitly waives):

| Gate | Check |
|------|-------|
| G1 | Every join's dimension-side key passes uniqueness/fanout check |
| G2 | No measure lacks its `-- DAX:` provenance comment |
| G3 | No UNSUPPORTED or MANUAL_PORT measure in emitted spec |
| G4 | No parity MISMATCH unresolved; parity run on ≥ top-usage measures |
| G5 | All BLOCKER/HIGH model-coverage items decided or accepted |
| G6 | Metric View syntax verified against current Databricks docs |
| G7 | No window functions / correlated subqueries inside measures |
| G8 | Source profiling complete; varchar_numeric columns have try_cast |

## Change Request Schema

```json
{
  "reviewer": "pbi-unified-reviewer",
  "review_score": 72,
  "verdict": "APPROVE_WITH_CONDITIONS",
  "changes": [
    {
      "measure": "Total Sales",
      "finding": "B3",
      "severity": "HIGH",
      "reason": "bare division without try_divide",
      "new_sql": "try_divide(sum(source.amount), count(*))",
      "new_status": "reviewed"
    },
    {
      "measure": "RLS Filtered",
      "finding": "G3",
      "severity": "CRITICAL",
      "reason": "UNSUPPORTED measure in spec",
      "action": "drop"
    }
  ]
}
```

Apply with: `translate.py --apply-change-request change_request.json --workdir <wd>`
