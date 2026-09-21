---
name: pbi-to-databricks
description: >
  Convert a Power BI semantic model (XMLA endpoint / TOM / .bim / .json scan, Tabular
  Editor export, or pbip TMDL) into a governed Databricks Unity Catalog Metric View
  (Mode A) or regular SQL gold schema objects (Mode B — Delta tables, views, materialized
  views). Includes per-measure confidence scoring (0–100), tiered DAX→Spark SQL
  translation, A–F complexity classification, source table profiling, numeric parity
  harness, automated review with acceptance gates (G1–G8), change-request loop, wrapper
  view generation for time intelligence and ratio-of-total measures, Excel source→target
  conversion report, and Genie Agent readiness guidance.
  Use this whenever the user mentions migrating/converting/recreating a Power BI dataset,
  semantic model, or DAX measures onto Databricks, Unity Catalog, Metric Views, or
  Genie — including phrases like "port this .bim", "translate these DAX measures",
  "rebuild this Power BI model in Databricks", "semantic model migration", "what's the
  conversion confidence", or when a .bim/.json/TMDL model scan is provided. Also use
  when a reviewer hands back a change_request.json to apply.
---

# Power BI Semantic Model → Databricks (Metric View + Regular SQL)

Converts an introspected Power BI model into either a **UC Metric View** (Mode A) or
**regular SQL gold schema** (Mode B), plus a full evidence trail: what converted cleanly,
what needs a human, how confident each translation is, and how to prove numeric parity.

## Pipeline (artifacts are the contract)

Work in `./conversion/<model_name>/`. Each stage writes a JSON artifact the next stage
reads — never skip a stage or hand-draft its output.

| # | Stage | Script | Output |
|---|-------|--------|--------|
| 1 | Extract | `scripts/extract_model.py` | `model.json` |
| 2 | Inventory + dependency graph | `scripts/dax_inventory.py` | `inventory.json` |
| 3 | Source table profiling + gap analysis | `scripts/profile_tables.py` | `profile.json`, `table_map.json`, `missing_tables.sql`, `gap_report.md` |
| 4 | Classify + confidence score | `scripts/classify_score.py` | `classification.json` |
| 5 | Tiered translation | `scripts/translate.py` | `translations.json` |
| 6 | Build metric views | `scripts/build_view.py` | `metric_view[_<fact>].yaml`, `create_view[_<fact>].sql`, `conversion_details.xlsx` |
| 6b | Wrapper views | `scripts/build_wrapper.py` | `wrapper_view[_<fact>].sql` (adds sheet to `conversion_details.xlsx`) |
| 7 | Parity harness | `scripts/reconcile.py` | `parity_queries/`, `parity_results.json` |
| 8 | Report + manifest | `scripts/report.py` | `conversion_report.md`, `conversion_manifest.json` |

**Shared utilities**: All scripts import from `scripts/_shared.py` for consistent
`snake()` case conversion, `split_args()` (paren-depth-aware DAX argument splitter),
`load_json()`, `save_json()`, and `save_text()`. The `openpyxl` package is required for
Excel report generation in build_view.py and build_wrapper.py.

## Execution Flow

### Step 0: User Inputs & Setup

Collect from the user before starting:

1. **Conversion mode**: Mode A (UC Metric View — YAML spec, dynamic grain, MEASURE() composability) or Mode B (Regular SQL — Delta tables, views, MVs, gold schema with fact_/dim_/vw_/mv_/pbi_/gold_ prefixes).
2. **Delivery mode**: (1) Code files only (dry-run, review before execution) or (2) Execute on target (requires live connection).
3. **Target**: Directory path for code files, or `catalog.schema` for live execution.
4. **Source tables available?** Y = UC catalog scan exists; N = will profile by name only.
5. **Source input**: Path to `.bim`, TMDL folder, or XMLA server + database name.

### Step 1: Extract (extract_model.py)

```
python scripts/extract_model.py --bim model.bim --workdir conversion/<model> --strict
```

Produces `model.json` with tables, columns, measures (with DAX), relationships, and
model features. Cross-checks integrity: duplicate names, empty DAX, orphan relationships.
TMDL is best-effort only (warns about lost dtypes/calc cols/hierarchies/RLS).
**Never reconstruct a model from a dashboard description.**

### Step 2: Inventory + Dependency Graph (dax_inventory.py)

```
python scripts/dax_inventory.py --workdir conversion/<model>
```

Produces `inventory.json`: per-measure function list, table/column references, measure
dependencies (topological order), CALCULATE filter classification, VAR usage, iterator
patterns. Cycles force MANUAL_PORT.

### Step 3: Source Table Profiling (profile_tables.py)

**Read `references/source-table-analysis.md` first** — never let `table_map.json` be a guess.

```
python scripts/profile_tables.py --workdir conversion/<model> --catalog-scan scan.json
```

Produces `profile.json`, `table_map.json` (seed), `missing_tables.sql`, `gap_report.md`.
Detects VARCHAR-numeric and string-date type mismatches with 80% sample threshold.
Without `--catalog-scan`, all matches are marked unverified.

**`table_map.json` structure** (critical for downstream stages):
- `physical`: PBI table name → `catalog.schema.table` mapping
- `fact`: primary fact table name
- `fact_groups`: list of fact tables, each with `name`, `view_name`, `aliases`
- `aliases`: PBI table name → SQL alias mapping
- `view_name`: target metric view name (e.g., `catalog.schema.model_metrics`)

### Step 4: Classify + Score (classify_score.py)

**Read `references/dax-translation-catalog.md` and `references/confidence-scoring.md` first.**

```
python scripts/classify_score.py --workdir conversion/<model>
```

Produces `classification.json`: per-measure 0–100 score, band (AUTO/AUTO_SPOT_CHECK/
NEEDS_REVIEW/MANUAL_PORT/UNSUPPORTED), tier (T1–T4), A–F category, and reasons.
Scores propagate through the dependency graph (weakest-link rule).

### Step 5: Translate (translate.py)

**Read `references/dax-translation-catalog.md` for function mappings and patterns.**

```
python scripts/translate.py --workdir conversion/<model>
```

Produces `translations.json`: tiered DAX→Spark SQL per measure.
- **T1**: Mechanical regex (SUM, COUNT, DIVIDE→try_divide, scalar functions)
- **T2**: Pattern rewrite (CALCULATE→FILTER, ISBLANK→IS NULL, iterators)
- **T3**: Template with `-- REVIEW` markers (time intelligence, ALL-family, LOOKUPVALUE)
- **T4**: Stub (manual port required)

The assistant refines T2/T3 SQL by hand in `translations.json` — the script produces
honest baselines + markers, not magic.

**Fact-group detection**: Each measure is assigned to a fact group based on:
1. PBI home table (where the measure is defined in the PBI model) — preferred if it's a real fact table
2. DAX aggregation target (which table the measure's SUM/COUNT/etc. references) — fallback
3. Measure dependency chain (inherits from referenced measures) — last resort

Dimension-named tables (Dim-*, Date, Calendar, Lookup) are deprioritized as fact-group
targets. Measures like `DISTINCTCOUNT('Dim-Location'[Country])` are assigned to the fact
table they're defined on (e.g., `Fact-Assignment`), not to the dimension they reference.

### Step 6: Build Output (build_view.py)

**Read `references/metric-view-yaml-spec.md` for Mode A, `references/regular-sql-patterns.md` for Mode B.**

Mode A (default):
```
python scripts/build_view.py --workdir conversion/<model>
```

Produces per fact group:
- `metric_view[_<fact>].yaml` (version 1.1) — only auto-converted measures (`auto`,
  `auto_spot_check`, `reviewed`). Single-fact models produce `metric_view.yaml`;
  multi-fact models produce `metric_view_<fact>.yaml` per fact group.
- `create_view[_<fact>].sql` — dry-run DDL with `CREATE OR REPLACE VIEW ... WITH METRICS`.
- `conversion_details.xlsx` — Excel workbook (requires `openpyxl`):
  - **Converted Measures** — all measures in the YAML with source DAX, target SQL, status,
    score, fact table, description, folder.
  - **Manual Review Required** — measures excluded from the YAML with original DAX, stub
    SQL, category, notes, and exclusion reason.

**Measure YAML format**:
```yaml
- name: Gross Profit
  description: Sales minus product cost     # human-readable PBI description only
  expr: |-                                  # pure Databricks SQL, block scalar for multi-line
    MEASURE(`Total Sales`)
    - MEASURE(`Total Cost`)
```
- `description`: PBI model description (omitted if none). **NOT for DAX provenance.**
  DAX source→target mapping lives in `conversion_details.xlsx`.
- `expr`: Final Databricks SQL expression. Multi-line expressions use PyYAML block scalar
  `|-` style (via custom `_LiteralStr` class). Trailing whitespace is stripped from each
  line to prevent PyYAML double-quote fallback.

**Semantic measure filter**: Before including a measure in the YAML, `build_view.py` checks
for PBI visual-layer patterns that passed translation as syntactically simple but are
semantically wrong for a metric view:
- `SELECTEDVALUE()` — a DAX visual-layer function with no metric view equivalent
- Static string literals (`"some text"`) — not aggregations
- String concatenation without aggregation (`"Title: " & column`) — PBI report formatting

These are routed to the Manual Review sheet with specific reasons.

Mode B:
```
python scripts/build_view.py --workdir conversion/<model> --mode-b
```
Produces numbered `.sql` files: dimension views, fact view, star join, measure views, gold wide view.

**Read `references/optimization-guide.md`** when drafting the spec, not after — several
optimizations (pre-aggregation, date-dim prep) change what SQL you emit.

### Step 6b: Wrapper Views (build_wrapper.py)

```
python scripts/build_wrapper.py --workdir conversion/<model>
```

Generates wrapper views that sit ON TOP of metric views, using window functions, LAG/LEAD,
RANK, and CTEs for measures that cannot be expressed as metric view `expr` but can be
automated from their DAX pattern. These boost KPI coverage beyond what metric views alone
provide.

**Supported patterns** (classified from original DAX):

| DAX Pattern | SQL Wrapper | Example |
|-------------|-------------|---------|
| SAMEPERIODLASTYEAR | `LAG(MEASURE(), 12) OVER (ORDER BY date)` | Revenue Prior Year |
| DATEADD(-N, MONTH) | `LAG(MEASURE(), N) OVER (ORDER BY date)` | Amount Prior Month |
| TOTALYTD | `SUM(MEASURE()) OVER (PARTITION BY year ORDER BY date ROWS UNBOUNDED PRECEDING)` | Revenue YTD |
| TOTALQTD | `SUM(MEASURE()) OVER (PARTITION BY year,quarter ORDER BY date ...)` | Amount QTD |
| TOTALMTD | `SUM(MEASURE()) OVER (PARTITION BY year,month ORDER BY date ...)` | Amount MTD |
| CALCULATE + ALL | `try_divide(MEASURE(), SUM(MEASURE()) OVER ())` | Pct of Total |
| RANKX | `DENSE_RANK() OVER (ORDER BY MEASURE() DESC)` | Provider Rank |
| YoY/MoM change | `base - prior` or `try_divide(base - prior, prior)` | YoY Change % |

Produces per fact group:
- `wrapper_view[_<fact>].sql` — `CREATE OR REPLACE VIEW ... AS SELECT` with:
  - Date dimension columns for GROUP BY grain
  - Base measures from the metric view (via `MEASURE()`)
  - Window function columns for each wrapped measure
- Adds a **Wrapper Views** sheet to `conversion_details.xlsx` with pattern, sub-type,
  original DAX, generated SQL, and status (WRAPPED or SKIPPED with reason).

**Requirements for wrapping**: The measure must (1) have a recognizable DAX time-intelligence
or ALL-family pattern, (2) reference a base measure that exists in the metric view, and
(3) for time-intelligence patterns, the fact table must have a date dimension join with
year/month/quarter columns. Measures failing any condition are SKIPPED with a reason.

### Step 7: Validate + Review

#### 7.1 Parity Harness
```
python scripts/reconcile.py --workdir conversion/<model> --emit --slices "Dim1,Dim2"
```
Generates paired DAX/SQL test queries + join grain checks. User runs queries, collects results.
```
python scripts/reconcile.py --workdir conversion/<model> --compare
```
Compares results (tolerance: abs≤0.01 OR rel≤1e-4), updates classification scores.

#### 7.2 Automated Review
**Read `references/review-rubric.md` first.**
```
python scripts/review.py --manifest conversion/<model>/conversion_manifest.json
```
Structural validation, measure lint, optimization lint → `review_findings.json`.

#### 7.3 Assistant Re-derivation
For every AUTO_SPOT_CHECK and NEEDS_REVIEW measure: independently re-derive SQL from
the `original_dax` and diff against the converter's SQL. Disagreements become findings
with proposed SQL.

#### 7.4 Change Request Loop (max 3 iterations)
```
python scripts/make_change_request.py --findings conversion/<model>/review_findings.json
python scripts/translate.py --apply-change-request conversion/<model>/change_request.json --workdir conversion/<model>
python scripts/build_view.py --workdir conversion/<model>
python scripts/build_wrapper.py --workdir conversion/<model>
python scripts/report.py --workdir conversion/<model>
```

#### 7.5 Gate Check → Verdict
**Acceptance gates** (REJECT if any fails, unless user waives):
- **G1** Every join's dimension-side key passes the uniqueness/fanout check.
- **G2** Every measure has DAX provenance in `conversion_details.xlsx`.
- **G3** No UNSUPPORTED or MANUAL_PORT measure included in the emitted YAML spec
  (enforced by default — `build_view.py` excludes them automatically).
- **G4** No parity MISMATCH unresolved; parity run on ≥ top-usage measures for production.
- **G5** All BLOCKER/HIGH model-coverage items decided or accepted by user.
- **G6** Metric View syntax verified against current Databricks docs (`docs_syntax_checked`).
- **G7** No window functions / correlated subqueries inside `measures[].expr`
  (window functions go in wrapper views, not metric view measures).
- **G8** Source table profiling completed with no unresolved BLOCKER gaps, and every
  `varchar_numeric`-flagged column feeding a measure is wrapped in `try_cast`.

### Step 8: Output + Report (report.py)
```
python scripts/report.py --workdir conversion/<model> --docs-checked 2026-09-14
```
Produces `conversion_report.md` + `conversion_manifest.json`:
- Coverage check (exhaustive enumeration — no silent drops)
- Manual checklist (scored, actionable)
- Per-measure detail table (score, band, category, parity, top reason)
- Parity results
- Optimization recommendations (model-specific)
- Testing patterns (5 structured tests)
- Genie readiness checklist

### Optional Step 9: Genie Agent Configuration
Read `references/genie-agent-config.md` for the 4-step setup:
knowledge store, instructions, verified answers, hard limits.

## Multi-Fact-Group Architecture

PBI models with multiple fact tables produce **one metric view per fact group**. Each
metric view has exactly one `source:` (a Databricks constraint), its own joins, dimensions,
and measures. The pipeline handles this automatically:

1. **`table_map.json`** lists all fact groups with their view names and aliases.
2. **`translate.py`** assigns each measure to a fact group based on PBI home table and
   DAX aggregation targets. Dimension-named tables are deprioritized.
3. **`build_view.py`** generates `metric_view_<fact>.yaml` per group (or `metric_view.yaml`
   for single-fact models). Shared dimensions appear in each view they join.
4. **`build_wrapper.py`** generates `wrapper_view_<fact>.sql` per group.
5. **`conversion_details.xlsx`** includes the fact table column so users know which
   metric view file each measure belongs to.

**Dimension duplication across views is by design** — each Databricks metric view is
self-contained with its own joins and dimensions. A dimension like `Dim-Date` that joins
to three fact tables appears in all three metric views. This is the Databricks model, not
a bug.

## Confidence Output (always produced)

Every measure gets a **0–100 score**, a **band**, a **tier**, and an **A–F category**:

| Score | Band | Tier | Meaning |
|-------|------|------|---------|
| 90–100 | AUTO | T1 | Mechanical translation, ship it |
| 70–89 | AUTO_SPOT_CHECK | T2 | Pattern-translated; spot-check 1–2 result slices |
| 40–69 | NEEDS_REVIEW | T3 | Candidate SQL emitted, human must approve |
| 11–39 | MANUAL_PORT | T4 | Templated stub only; a human writes the SQL |
| 0–10 | UNSUPPORTED | T4 | No Metric View equivalent (e.g. RLS logic) |

| Category | Pattern |
|----------|---------|
| A | Simple aggregation (SUM, COUNT, AVG — no complex patterns) |
| B | Derived measure (references other measures, pattern rewrites) |
| C | Time intelligence (SAMEPERIODLASTYEAR, DATESYTD, etc.) |
| D | Filtered aggregate (CALCULATE with filter arguments) |
| E | Semi-additive (LASTNONBLANK, CLOSINGBALANCEYEAR, etc.) |
| F | Complex/untranslatable (RLS, EARLIER, calc groups, RANKX, score < 40) |

## Build Output Summary

For each model conversion, the pipeline produces:

| Output | Stage | Purpose |
|--------|-------|---------|
| `metric_view[_<fact>].yaml` | 6 | Metric View YAML spec (auto-converted measures only) |
| `create_view[_<fact>].sql` | 6 | DDL to create the metric view (dry-run) |
| `wrapper_view[_<fact>].sql` | 6b | Wrapper views with window functions for excluded measures |
| `conversion_details.xlsx` | 6+6b | Three-sheet Excel: Converted, Manual Review, Wrapper Views |
| `conversion_report.md` | 8 | Human-readable coverage report |
| `conversion_manifest.json` | 8 | Machine-readable contract for reviewer |

## Non-negotiables

1. **Extract before translate.** Every downstream artifact traces to `model.json` from a
   real XMLA pull / .bim / TMDL export — never from a description of the dashboard.
2. **Exhaustive enumeration, never skimmed.** Count every measure at extraction, list
   them, and cross-check that count survives every stage.
3. **Source-first: profile the target catalog before writing any join, dimension, or
   measure.** `table_map.json`'s physical names are confirmed, never guessed.
4. **Classify from function inventory + AST patterns, never from DAX length.**
5. **Time intelligence is always flagged** — emit candidate against an explicit date
   dimension, marked `-- REVIEW`, never a silent port. Time-intelligence measures that
   pass semantic validation can be automated as wrapper views.
6. **`USERELATIONSHIP` / `TREATAS` / `CROSSFILTER` cap confidence** — they rewrite the
   join graph per-measure; a Metric View has one static join graph.
7. **Calculation groups are a model-level blocker** — surface immediately.
8. **RLS is never migrated implicitly.** Roles are inventoried and reported; UC row
   filters / column masks are a separate deliverable.
9. **DAX provenance lives in `conversion_details.xlsx`**, not in the metric view YAML.
   The `description` field is for human-readable PBI descriptions only — putting DAX
   source in description would affect Databricks dimension/measure detection.
10. **Bi-directional and many-to-many relationships are flagged**, dimension-side join
    keys must be uniqueness-checked.
11. **Generation is separate from execution.** DDL is dry-run by default.
12. **`try_divide` for DIVIDE translation** — NULL-correct (matches DAX BLANK semantics)
    and Photon-optimized. Not NULLIF.
13. **Semantic validation before YAML inclusion.** Measures with SELECTEDVALUE, static
    strings, or string concatenation without aggregation are excluded from the metric view
    regardless of their translation status — they are PBI visual-layer formatting, not metrics.
14. **Fact-group assignment respects PBI model structure.** Measures are assigned to the
    fact table where they're defined in PBI, not to dimension tables they reference in
    their DAX aggregation targets.

## Reviewer Loop (built-in Step 7)

The review is Step 7 of the pipeline, not a separate skill. The automated review
(`review.py`) catches mechanical issues; the assistant re-derives SQL for flagged
measures. Change requests flow through `change_request.json` so the revision trail
survives. Max 3 iterations before escalating to the user.

## When Information Is Missing

- No XMLA access and no export → ask for a `.bim`/TMDL export.
- No live Unity Catalog connection → run `profile_tables.py` without `--catalog-scan`;
  hand the user the `information_schema` query pack from `source-table-analysis.md`.
- No date dimension → time-intelligence measures stay ≤39; wrapper views cannot generate
  time-intelligence patterns. Offer date-dim DDL.
- No live Databricks connection → produce everything through stage 8, emit parity
  query pack for manual execution.

## Reference Documents

| Document | Contents |
|----------|----------|
| `references/dax-translation-catalog.md` | ~90 DAX functions, 4 tiers, scalar mappings, examples |
| `references/metric-view-yaml-spec.md` | YAML v1.1 spec: window, format, parameters, joins |
| `references/regular-sql-patterns.md` | Mode B gold schema: fact_/dim_/vw_/mv_/gold_ patterns |
| `references/pitfalls.md` | 50 Databricks-specific pitfalls (YAML, DAX translation, data quality) |
| `references/confidence-scoring.md` | 0–100 scoring: bands, caps, deductions, propagation |
| `references/model-coverage.md` | Feature matrix: calc groups, bi-di, M2M, RLS, perspectives |
| `references/source-table-analysis.md` | 5-phase profiling with SQL templates |
| `references/complex-functions.md` | 6 wrapper view templates for Cat F measures |
| `references/optimization-guide.md` | Pre-agg, liquid clustering, date-dim, partition pruning |
| `references/review-rubric.md` | Review checks A1–D8, gates G1–G8, severity weights |
| `references/genie-agent-config.md` | 4-step Genie Agent setup |
| `templates/wrapper_views.md` | 6 SQL templates: TOPN, RANKX, CONCATENATEX, Pct-of-Total, Moving Avg, YoY |
