# CLAUDE.md — pbi-unified Skill

This file provides guidance to Claude Code when working with the pbi-unified skill for
converting Power BI semantic models to Databricks Unity Catalog objects.

## Skill Architecture

This is a unified conversion skill that merges the best of two predecessor skills:
- **pbi-v1**: Exhaustive prose-based skill with 50 pitfalls, Mode B SQL patterns, Genie config
- **pbi-uc**: Script-driven pipeline with confidence scoring, parity harness, reviewer gates

The unified skill uses pbi-uc's Python pipeline as the execution backbone, enhanced with
pbi-v1's comprehensive reference documentation.

### Modes
- **Mode A** (default): UC Metric View (`CREATE VIEW ... WITH METRICS LANGUAGE YAML`) —
  dynamic grain, MEASURE() composability, semantic layer for BI tools and Genie.
- **Mode B**: Regular SQL gold schema — Delta tables, views, materialized views with
  fact_/dim_/vw_/mv_/gold_/pbi_ prefixes. Same pipeline through Step 4, branches at Step 6.

## Pipeline Scripts (in `scripts/`)

All scripts import from `_shared.py` for consistent `snake()` case conversion,
`split_args()` (paren-depth-aware DAX argument splitter), `load_json()`, `save_json()`,
and `save_text()`. The `openpyxl` package is required for Excel report generation.

| # | Script | Stage | Reads | Writes |
|---|--------|-------|-------|--------|
| 1 | `extract_model.py` | Extract | .bim/.tmdl/xmla | model.json |
| 2 | `dax_inventory.py` | Inventory | model.json | inventory.json |
| 3 | `profile_tables.py` | Profile | model.json + catalog scan | profile.json, table_map.json, missing_tables.sql, gap_report.md |
| 4 | `classify_score.py` | Classify | model.json + inventory.json | classification.json |
| 5 | `translate.py` | Translate | model+inv+cls+table_map | translations.json |
| 6 | `build_view.py` | Build views | model+translations+table_map | metric_view[_<fact>].yaml, create_view[_<fact>].sql, conversion_details.xlsx |
| 6b | `build_wrapper.py` | Wrapper views | model+translations+table_map+cls | wrapper_view[_<fact>].sql (adds sheet to xlsx) |
| 7 | `reconcile.py` | Parity | translations+table_map | parity_queries/, parity_results.json |
| 8 | `report.py` | Report | all above | conversion_report.md, conversion_manifest.json |
| 7.2 | `review.py` | Review | manifest+spec | review_findings.json |
| 7.3 | `make_change_request.py` | Change req | review_findings.json | change_request.json |

### Execution Commands

```bash
python scripts/extract_model.py --bim model.bim --workdir conversion/<model>
python scripts/dax_inventory.py --workdir conversion/<model>
python scripts/profile_tables.py --workdir conversion/<model>          # add --catalog-scan for live UC
python scripts/classify_score.py --workdir conversion/<model>
python scripts/translate.py --workdir conversion/<model>
python scripts/build_view.py --workdir conversion/<model>
python scripts/build_wrapper.py --workdir conversion/<model>
python scripts/reconcile.py --emit --workdir conversion/<model>
python scripts/report.py --workdir conversion/<model>

# Reviewer loop
python scripts/review.py --manifest conversion/<model>/conversion_manifest.json
python scripts/make_change_request.py --findings review_findings.json
python scripts/translate.py --apply-change-request change_request.json --workdir conversion/<model>
python scripts/build_view.py --workdir conversion/<model>
python scripts/build_wrapper.py --workdir conversion/<model>
python scripts/report.py --workdir conversion/<model>
```

## Multi-Fact-Group Architecture

PBI models with multiple fact tables produce **one metric view per fact group**:

1. **`table_map.json`** lists all fact groups with their view names and aliases
2. **`translate.py`** assigns each measure to a fact group based on:
   - PBI home table (where the measure is defined) — preferred if it's a true fact table
   - DAX aggregation target (which table the SUM/COUNT/etc. references) — fallback
   - Measure dependency chain (inherits from referenced measures) — last resort
3. **`build_view.py`** generates `metric_view_<fact>.yaml` per group (or `metric_view.yaml`
   for single-fact models)
4. **`build_wrapper.py`** generates `wrapper_view_<fact>.sql` per group

**Dimension-named tables** (Dim-*, Date, Calendar, Lookup) are deprioritized as fact-group
targets via `true_fact_names` filtering in `translate.py`. This prevents measures like
`DISTINCTCOUNT('Dim-Location'[Country])` from creating spurious dimension-sourced metric
views.

**Dimension duplication across views is by design** — each Databricks metric view is
self-contained with its own joins and dimensions. A dimension like `Dim-Date` that joins
to three fact tables appears in all three metric views.

## Fact-Group Detection (translate.py)

The `detect_fact_group()` function uses three prioritized strategies:

```
1. measure_home_table[name] ∈ true_fact_names  →  use home table
2. AGG_COL_RE matches in DAX (SUM/COUNT/etc. targets)  →  prefer true_fact_names > any fact
3. Tables from inventory  →  prefer true_fact_names > any fact
4. Measure dependency chain  →  inherit from referenced measures
5. Default to primary fact from table_map.json
```

Key data structures:
- `measure_home_table`: dict mapping measure name → PBI table where it's defined
- `true_fact_names`: fact_names minus dim-prefixed tables (dim/d_/dimension/lookup/date/calendar)
- `dim_prefix_re`: regex matching dimension-like table name prefixes

## Semantic Measure Filter (build_view.py)

Before including a measure in the YAML, `_invalid_measure_reason()` catches PBI
visual-layer patterns that are syntactically simple but semantically wrong for metric views:

| Pattern | Detection | Why excluded |
|---------|-----------|--------------|
| `SELECTEDVALUE()` | Regex on original DAX | DAX visual-layer function, no metric view equivalent |
| Static strings (`"text"`) | Translated SQL is quoted string literal | Not an aggregation |
| String concat without agg | `&` in DAX, no aggregation function | PBI report formatting, not a metric |

These are routed to the **Manual Review Required** sheet in conversion_details.xlsx with
specific reasons, not silently dropped.

## DAX Classification

| Cat | Name | Score Range | Pattern |
|-----|------|-------------|---------|
| A | Simple aggregation | 90–100 | SUM, COUNT, AVG, no complex patterns |
| B | Derived measure | 70–89 | References measures, IF/SWITCH/ISBLANK rewrites |
| C | Time intelligence | capped 35 | SAMEPERIODLASTYEAR, DATESYTD, DATEADD, etc. |
| D | Filtered aggregate | varies | CALCULATE with boolean/table/ALL filter args |
| E | Semi-additive | capped 35 | LASTNONBLANK, CLOSINGBALANCEYEAR, etc. |
| F | Complex/untranslatable | <40 or blocked | RLS, EARLIER, calc groups, RANKX |

Scores are primary (0–100); categories (A–F) are derived display labels.
Scores propagate through the dependency graph — weakest-link rule.

## Wrapper Views (build_wrapper.py)

Wrapper views sit ON TOP of metric views, using window functions for measures that
cannot be metric view `expr` but can be automated from their DAX pattern:

| DAX Pattern | SQL Wrapper | Sub-type |
|-------------|-------------|----------|
| SAMEPERIODLASTYEAR | LAG(MEASURE(), 12) OVER (ORDER BY date) | sply |
| DATEADD(-N, MONTH) | LAG(MEASURE(), N) OVER (ORDER BY date) | dateadd |
| TOTALYTD | SUM(MEASURE()) OVER (PARTITION BY year ORDER BY date ROWS UNBOUNDED PRECEDING) | ytd |
| TOTALQTD | Same, PARTITION BY year,quarter | qtd |
| TOTALMTD | Same, PARTITION BY year,month | mtd |
| CALCULATE + ALL | try_divide(MEASURE(), SUM(MEASURE()) OVER ()) | ratio |
| RANKX | DENSE_RANK() OVER (ORDER BY MEASURE() DESC) | rank |
| YoY/MoM change | base - prior or try_divide(base - prior, prior) | derived |

Requirements for wrapping: (1) recognizable DAX pattern, (2) base measure exists in
metric view, (3) date dimension join with year/month/quarter columns for time-intelligence.

## Build Output Format

**Metric View YAML** — only auto-converted measures (`auto`, `auto_spot_check`, `reviewed`):
```yaml
- name: Gross Profit
  description: Sales minus product cost     # human-readable PBI description only
  expr: |-                                  # block scalar for multi-line (via _LiteralStr)
    MEASURE(`Total Sales`)
    - MEASURE(`Total Cost`)
```
- `description`: PBI model description (omitted if none). **NOT for DAX provenance.**
- `expr`: Final Databricks SQL. Multi-line uses PyYAML block scalar `|-` via custom
  `_LiteralStr` class. `_strip_lines()` removes trailing whitespace to prevent
  PyYAML double-quote fallback.

**conversion_details.xlsx** — three sheets:
- **Converted Measures**: measures in the YAML with source DAX, target SQL, status, score,
  fact table, description, folder
- **Manual Review Required**: excluded measures with original DAX, stub SQL, category, notes,
  exclusion reason
- **Wrapper Views**: measures covered by wrapper views with pattern, sub-type, base measure,
  original DAX, generated SQL, status (WRAPPED or SKIPPED with reason)

## Critical Databricks Rules

1. **Metric View measures must be plain aggregates** — no window functions, no subqueries,
   no correlated references. Window/ratio logic goes in wrapper views or consumer queries.
2. **Window `order:` must reference named fields** (dimensions defined in the spec), not raw
   column references. This is the most dangerous silent-failure pitfall.
3. **`try_divide(num, denom)` for DIVIDE** — returns NULL on zero (matches DAX BLANK).
   Not `NULLIF(denom, 0)`. Photon-optimized.
4. **No `IFF()`** — Databricks uses `IF()` or `CASE WHEN`. `IFF()` is Snowflake-only.
5. **Backtick quoting** for identifiers: `` `My Column` ``, not `[My Column]` or `"My Column"`.
6. **`version: 1.1`** in YAML spec (not 0.1).
7. **ALTER VIEW AS $$ ... $$ IS supported** and preserves grants — preferred over
   CREATE OR REPLACE which drops them.
8. **`trailing`/`leading` ranges EXCLUDE the anchor row.** Use `trailing 8 day` for
   7 days + current.
9. **Topological order for translation** — translate leaf measures first so dependencies
   can reference via MEASURE().
10. **VAR/RETURN → inline or decompose** — Spark SQL has no VAR equivalent; inline the
    expression or split into helper measures.
11. **Cannot combine `window:` with `FILTER WHERE`** on the same measure.
12. **Window measures are terminal** — cannot be referenced by `MEASURE()`.
13. **`'on':` must be single-quoted in YAML** — `on` is a YAML reserved word.
13. **Parameters make views non-materializable.**
14. **RLS + materialization are mutually exclusive** (SQLSTATE 42K0E).

## Acceptance Gates (G1–G8)

| Gate | Check | Severity |
|------|-------|----------|
| G1 | Join dimension keys are unique (no fanout) | CRITICAL |
| G2 | Every measure has DAX provenance in conversion_details.xlsx | HIGH |
| G3 | No MANUAL_PORT/UNSUPPORTED in emitted YAML (enforced by default) | CRITICAL |
| G4 | No parity MISMATCH unresolved | CRITICAL |
| G5 | All BLOCKER/HIGH model items decided | HIGH |
| G6 | Syntax verified against current Databricks docs | HIGH |
| G7 | No window/subquery in measure exprs (→ wrapper views) | CRITICAL |
| G8 | Source profiling complete, varchar_numeric has try_cast | CRITICAL |

## Reference File Index

| File | Purpose |
|------|---------|
| `references/dax-translation-catalog.md` | Function mappings (DAX→Spark SQL), ~90 functions |
| `references/metric-view-yaml-spec.md` | YAML v1.1 spec with window/format/join details |
| `references/regular-sql-patterns.md` | Mode B gold schema patterns |
| `references/pitfalls.md` | 50 Databricks-specific pitfalls |
| `references/confidence-scoring.md` | 0–100 scoring methodology |
| `references/model-coverage.md` | Feature coverage matrix |
| `references/source-table-analysis.md` | 5-phase profiling checklist |
| `references/complex-functions.md` | 6 wrapper view templates (Cat F) |
| `references/optimization-guide.md` | Performance optimization guidance |
| `references/review-rubric.md` | Review checks A1–D8, gates G1–G8 |
| `references/genie-agent-config.md` | Genie Agent setup (4 steps) |
| `templates/wrapper_views.md` | 6 SQL templates: TOPN, RANKX, CONCATENATEX, Pct-of-Total, Moving Avg, YoY |

## Common Pitfall Reminders

- **Fanout joins** silently inflate every measure — always run grain_checks.sql
- **BLANK ≠ NULL**: DAX BLANK is closer to NULL but interacts differently with aggregation
- **CALCULATE context transition**: verify every filter arg in translated SQL
- **Date tables must be explicit** in Metric View (PBI auto-detects, Databricks doesn't)
- **FORMAT strings differ**: DAX `"#,##0.00"` ≠ Spark `number_format(x, 2)`
- **TMDL extraction is lossy**: no dtypes, calc columns, hierarchies, or RLS — prefer .bim
- **Dimension-sourced metric views**: if `detect_fact_group()` assigns measures to dim tables,
  check `true_fact_names` filtering — likely a dim-prefixed table slipping through
