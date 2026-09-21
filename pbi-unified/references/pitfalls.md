# Pitfalls, Validation Rules, and Untranslatable DAX Components

50 numbered pitfalls from production experience. Items 1–13 are platform-agnostic.
Items 14–50 are **Databricks-specific**. Every pipeline run should cross-check the
generated YAML/SQL against this list.

---

## 1. Common Pitfalls

| # | Pitfall | Consequence | Fix |
|---|---------|-------------|-----|
| 1 | Skimming measures instead of exhaustive enumeration | 50–70% of measures silently dropped | Complete inventory fully; count and cross-check before any YAML |
| 2 | Column order mismatch between CSV and CREATE TABLE | Data loads into wrong columns silently | Read CSV header first; define columns in exact positional order |
| 3 | Not adding SYNONYMS / display_name to measures | Genie cannot match natural-language queries | Add `synonyms:` entries for common aliases on every measure and field |
| 4 | Not adding DAX traceability in comments | No audit trail for PBI-to-metric mapping | Always add `-- DAX: <expr>` above every translated expression |
| 5 | Using derived measures where simple would work | Unnecessary composition constraints | Prefer Category A (simple aggregate) over composed when possible |
| 6 | Calculated table columns (`type: "calculated"`) overlooked | Missing PBI-computed columns | Recreate as fields with `expr:` in YAML |
| 7 | Classifying SAMEPERIODLASTYEAR measures as Category B | Wrong measure type, incorrect output | If ANY measure in the chain is Cat C, the whole chain is Cat C |
| 8 | Non-physical tables excluded from measure enumeration | Measures on those tables dropped | Enumerate from ALL non-internal tables |
| 9 | Skipping input integrity validation | Hours wasted on unusable input | Always validate before generating YAML |
| 10 | Proceeding with DirectQuery export | Incomplete schema — missing columns, empty expressions | Re-export in Import or Dual mode |
| 11 | Input with zero fact candidates | Nothing to aggregate | Verify PBI has numeric columns with `summarizeBy != 'none'` |
| 12 | Circular relationships in input | View creation fails | Detect cycles; fix in PBI first |
| 13 | Data type mismatch on join keys | Join returns 0 rows | Ensure both sides are same type (INT to INT, STRING to STRING) |
| 14 | **Window measure `order:` references source column instead of named field** | **Silently produces WRONG RESULTS (no error!)** | Always reference a named `fields:` entry, never the raw source column |
| 15 | **Forward reference in YAML measures** | DDL creation fails or undefined behavior | Topologically sort measures by dependency — referenced measures first |
| 16 | **Day-based offset with variable-length months** | -1 month from Jan 31 does not land on Dec 31 | Use month-level fields for monthly comparisons |
| 17 | **Trailing/leading range excludes anchor row** | Off-by-one in rolling calculations (trailing 7 day = 7 days BEFORE current, not including) | Use `trailing 8 day` to include current row, or append `inclusive` |
| 18 | **Semiadditive still sums across non-order dimensions** | Inventory balance summed across products gives inflated total | Expected behavior; use for "last per X, summed across Y" |
| 19 | **FILTER propagation in composed measures** | `MEASURE(m1/m2) FILTER WHERE` pushes filter into BOTH m1 AND m2 | May not be desired for denominator; split into separate queries |
| 20 | **RLS + materialization mutual exclusion** | SQLSTATE 42K0E error | Must choose security OR materialization, not both |
| 21 | **Parameterized views cannot be materialized** | Materialization setup fails | Remove parameters or skip materialization for that view |
| 22 | **PBI BI Compatibility Mode removed from connector** | Existing PBI reports break after migration | Use Native Query with `MEASURE()` or wrapper views |
| 23 | **Using `dimensions` keyword instead of `fields`** | YAML parse error or DDL failure | YAML v1.1 uses `fields:`, not `dimensions:` |
| 24 | **`on` not quoted in YAML joins** | YAML parse error (`on` is a reserved YAML keyword) | Use `'on':` with single quotes |
| 25 | **STRING columns containing numeric data** | SUM() fails or returns NULL | `CAST(col AS DECIMAL(38,2))` or `TRY_CAST(col AS DECIMAL(38,2))` |
| 26 | **STRING columns with comma-formatted numbers** | "1,016.00" fails cast | `CAST(REPLACE(col, ',', '') AS DECIMAL(38,2))` then aggregate |
| 27 | **STRING columns containing dates** | Join/filter fails | `TRY_CAST(col AS DATE)` or `TO_DATE(col, 'MM/dd/yyyy')` |
| 28 | **Missing prior year data** | vPY / SPLY window offset returns NULL | Document limitation in measure `description:` field |
| 29 | **Single week of data** | L4 = L13 = YTD (all produce same value) | Document in measure `description:` field; warn consumers |
| 30 | **Column names with special characters** | SQL error on unquoted reference | Use backtick quoting: `` `MFG #` ``, `` `Cost W/HC` `` |
| 31 | **Using IFF() in Databricks** | Syntax error — Databricks does NOT have IFF | Use `CASE WHEN cond THEN x ELSE y END` |
| 32 | **Duplicate field/measure names across YAML** | DDL compilation error | Ensure unique names across all fields and measures in the view |
| 33 | **More than one source table** | YAML only supports single `source:` | Create a pre-joined view as source or use the `joins:` block |
| 34 | **Many-to-many join in YAML** | Not supported; DDL error | Restructure to many-to-one or create a bridge table |
| 35 | **Cross-view MEASURE() queries** | Not supported; runtime error | Each metric view is self-contained; cannot reference measures across views |
| 36 | **No PRIVATE fields or measures** | Intermediate calculations exposed to consumers | Cannot hide; consider a separate utility view for intermediates |
| 37 | **Metric view with 100+ measures — no partial update** | Must resubmit entire YAML for any change | Maintain YAML source in version control; automate deployment |
| 38 | **ALTER VIEW vs CREATE OR REPLACE** | Using CREATE OR REPLACE drops grants | Use `ALTER VIEW ... AS $$` for updates — it preserves existing grants |
| 39 | **MEASURE() cannot be used with OVER** | Cannot compute window aggregations at query time | Define as window measures in YAML instead |
| 40 | **MEASURE() FILTER requires Runtime 18.1+** | Runtime error on older clusters | Check cluster runtime version before using FILTER clause |
| 41 | **Global `filter:` cannot be bypassed** | `filter:` clause applies to ALL queries against the view | If some queries need unfiltered data, create a separate view without `filter:` |
| 42 | **No COUNT DISTINCT rollup in materialization** | Non-additive measures always fall through to source table | Expect slower performance for COUNT DISTINCT measures |
| 43 | **Owner locked after materialization** | Cannot transfer ownership of materialized metric view | Plan ownership before enabling materialization |
| 44 | **YEARWEEK arithmetic crossing year boundary** | `202601 - 4 = 202597` (wrong — should be `202549`) | Never use integer YEARWEEK arithmetic; use `DATE_SUB(date, INTERVAL 4 WEEK)` |
| 45 | **BOOLEAN columns stored as strings** | `WHERE is_active = TRUE` fails on VARCHAR "true"/"false" | Use `WHERE LOWER(is_active) = 'true'` or `TRY_CAST(is_active AS BOOLEAN)` |
| 46 | **Date table does not cover fact data range** | Window measures return NULL for dates outside dim_date | Validate `MIN(fact.date) >= MIN(dim_date.date_key)` and MAX equivalently |
| 47 | **Duplicate primary keys in dimension table** | Joins produce inflated row counts (fan-out) | `SELECT pk, COUNT(*) FROM dim GROUP BY pk HAVING COUNT(*) > 1` before joining |
| 48 | **Orphan foreign keys in fact table** | Rows silently dropped by INNER JOIN or NULL in LEFT JOIN | Check `SELECT COUNT(*) FROM fact f LEFT JOIN dim d ON f.fk = d.pk WHERE d.pk IS NULL` |
| 49 | **VALUES() in DAX filter context not documented** | Developer tries to translate VALUES() literally | VALUES() is implicit in SQL GROUP BY — no translation needed |
| 50 | **Nested aggregation in YAML measure** | `AVG(SUM(col))` fails — YAML measures allow exactly ONE aggregation level | Use wrapper view with CTE: inner CTE does SUM, outer does AVG |

### Additional Pitfalls (from pipeline experience)

| # | Pitfall | Consequence | Fix |
|---|---------|-------------|-----|
| 51 | **Duplicated snake() implementations across scripts** | Name drift — same PBI column maps to different snake_case in different stages | Single snake() in `_shared.py`, imported everywhere |
| 52 | **VARCHAR-numeric columns not detected before translation** | Translated SQL references `sum(col)` on a string column → NULL result | Run `profile_tables.py` with `--catalog-scan` before translate step |
| 53 | **YAML version set to 0.1** | Outdated spec; missing feature support | Always use `version: 1.1` |

---

## 2. Validation Rules Quick Reference

26 rules covering MEASURE() restrictions, YAML constraints, and DDL constraints.

| # | Rule | Violation Symptom |
|---|------|-------------------|
| 1 | Measures must use aggregate functions (SUM, COUNT, AVG, MIN, MAX) or MEASURE() | Compilation error |
| 2 | MEASURE() cannot be used with OVER clause | Runtime error |
| 3 | MEASURE() FILTER requires Runtime 18.1+ | Runtime error on older clusters |
| 4 | FILTER propagates recursively into all composed measures | Unexpected results (not an error) |
| 5 | Window measure `order:` must reference a named field, not a source column | Silent wrong results |
| 6 | Window measures: trailing/leading ranges exclude the anchor row | Off-by-one in rolling calculations |
| 7 | Forward references in measures are not supported | DDL error or undefined behavior |
| 8 | Circular references between measures | DDL error |
| 9 | `source:` must reference exactly one table | DDL error |
| 10 | Joins must be many-to-one (fact to dimension direction) | DDL error |
| 11 | `'on':` must be quoted in YAML (reserved keyword) | YAML parse error |
| 12 | Fields cannot reference measures | DDL error |
| 13 | Parameters make views non-materializable | Materialization error |
| 14 | RLS or column masks prevent materialization | SQLSTATE 42K0E |
| 15 | Cannot rename materialized metric views | DDL error |
| 16 | Only one unaggregated materialization allowed per view | Materialization error |
| 17 | Schedule changes do not trigger materialization refresh | Stale data served silently |
| 18 | Group ownership not supported for materialized views | Permission error |
| 19 | Measure names must be unique across the entire view | DDL error |
| 20 | Field names must be unique across the entire view | DDL error |
| 21 | Cannot combine window spec with FILTER WHERE on same measure | DDL error |
| 22 | Semiadditive still sums across non-order dimensions | Unexpected totals (not an error) |
| 23 | Day offset does not respect variable month lengths | Wrong period comparison |
| 24 | COUNT DISTINCT cannot use materialization rollup | Performance degradation |
| 25 | Multi-aggregate expressions cannot use rollup | Performance degradation |
| 26 | YAML version must be 1.1 | DDL error |

---

## 3. Untranslatable DAX Components

These DAX patterns have NO Databricks UC Metric View equivalent. Each requires
either architectural redesign or pre-computation in a staging view.

| # | DAX Component | Reason | Recommendation |
|---|---------------|--------|----------------|
| 1 | Calculation Groups | No dynamic measure selection in metric views | Redesign as separate measures per variant |
| 2 | Context Transition | No row-to-filter context switch | Pre-aggregate in base table or staging view |
| 3 | USERELATIONSHIP | No active/inactive relationship concept | Create separate joins per relationship path in YAML |
| 4 | CROSSFILTER | No dynamic cross-filter direction | All joins are one-directional; model accordingly |
| 5 | PATH/PATHITEM/PATHCONTAINS | No recursive hierarchy support | Flatten hierarchy in base table (parent-child to level columns) |
| 6 | ADDCOLUMNS/SUMMARIZE (as table functions) | No virtual table creation in YAML | Pre-compute in staging view |
| 7 | ISINSCOPE | No query-grain detection | Measures cannot vary behavior by query grain; create grain-specific measures |
| 8 | ISFILTERED/ISCROSSFILTERED | No filter-state detection | Not translatable; redesign measure logic |
| 9 | ALLSELECTED | No visual-context scope | Not translatable; no equivalent concept |
| 10 | TREATAS | No virtual relationships | Must create actual join in YAML `joins:` block |
| 11 | GENERATE/GENERATEALL | No cartesian product with row context | Pre-compute in staging view |
| 12 | NATURALINNERJOIN/NATURALLEFTOUTERJOIN | DAX-specific join semantics | Use YAML `joins:` block with explicit keys |
| 13 | CALCULATE with ALL (full filter removal) | No dynamic filter removal at query time | Separate unfiltered measure |
| 14 | CALCULATE with ALLEXCEPT | Partial filter removal not supported | Separate GROUP BY in staging view |
| 15 | RANKX with ALL | No window functions inside MEASURE() | Wrapper view with `RANK() OVER (...)` |
| 16 | TOPN | No dynamic top-N in YAML | Wrapper view with `ORDER BY ... LIMIT N` |
| 17 | CONCATENATEX | String aggregation not a measure | Wrapper view with `CONCAT_WS(sep, COLLECT_LIST(col))` |

---

## 4. Data Quality Pitfalls

PBI silently coerces types at import time. A column that works as SUM in PBI may be
VARCHAR in the source table. Always run detection queries before writing expressions.

| # | Issue | Detection | Fix |
|---|-------|-----------|-----|
| 1 | STRING columns containing numeric values | `TRY_CAST(col AS DECIMAL(38,2))` | `CAST(col AS DECIMAL(38,2))` in field `expr:` |
| 2 | STRING columns containing dates | `TRY_CAST(col AS DATE)` | `TRY_CAST(col AS DATE)` or `TO_DATE(col, fmt)` |
| 3 | Comma-formatted numeric strings | `WHERE col LIKE '%,%'` | `CAST(REPLACE(col, ',', '') AS DECIMAL(38,2))` |
| 4 | Mixed types in same column | `SELECT TYPEOF(col), COUNT(*) GROUP BY 1` | Cast to dominant type |
| 5 | Join key type mismatch | Compare `TYPEOF(f.key)` vs `TYPEOF(d.key)` | Cast in `'on':` expression |
| 6 | NULL-heavy columns in aggregation | `COUNT(*) - COUNT(col)` | `COALESCE(col, 0)` in measure |
| 7 | Duplicate PKs in dimension | `GROUP BY pk HAVING COUNT(*) > 1` | Deduplicate before joining |
| 8 | Date range mismatch | `LEFT JOIN dim_date ... WHERE d.date_key IS NULL` | Extend dim_date to cover full range |
| 9 | Orphan foreign keys | `LEFT JOIN dim ... WHERE d.pk IS NULL AND f.fk IS NOT NULL` | Fix source or use LEFT JOIN |

---

## 5. ALTER VIEW — Production Update Path

`ALTER VIEW catalog.schema.view_name AS $$ <yaml> $$` is supported for metric views
and **preserves existing grants**. This is the preferred production update path.

`CREATE OR REPLACE VIEW` also works but **drops and recreates grants**.

Use `ALTER VIEW` for all updates after initial deployment.

```sql
-- Initial creation
CREATE OR REPLACE VIEW catalog.schema.my_metric_view
WITH METRICS LANGUAGE YAML AS $$
version: 1.1
source: catalog.schema.base_table
fields:
  - name: region
    expr: region_name
    synonyms: [territory, area]
measures:
  - name: total_revenue
    expr: SUM(revenue)
    description: "Total revenue across all orders"
$$;

-- Subsequent updates (preserves grants)
ALTER VIEW catalog.schema.my_metric_view AS $$
version: 1.1
source: catalog.schema.base_table
fields:
  - name: region
    expr: region_name
    synonyms: [territory, area]
measures:
  - name: total_revenue
    expr: SUM(revenue)
    description: "Total revenue across all orders"
  - name: order_count
    expr: COUNT(*)
    description: "Total number of orders"
$$;
```

---

## 6. Databricks vs Snowflake Syntax Traps

| # | Snowflake Syntax | Databricks Equivalent | Notes |
|---|------------------|-----------------------|-------|
| 1 | `IFF(cond, x, y)` | `CASE WHEN cond THEN x ELSE y END` | No IFF in Databricks |
| 2 | `DIV0(a, b)` | `try_divide(a, b)` or `CASE WHEN b = 0 THEN 0 ELSE a/b END` | try_divide returns NULL, not 0 |
| 3 | `NVL(a, b)` | `COALESCE(a, b)` | NVL works but COALESCE is idiomatic |
| 4 | `TRY_TO_NUMBER(x)` | `TRY_CAST(x AS DECIMAL(38,2))` | Different function name |
| 5 | `SELECT * FROM SEMANTIC_VIEW(sv)` | `SELECT MEASURE(m) FROM view GROUP BY f` | Different query paradigm |
| 6 | `"double quotes"` for identifiers | `` `backticks` `` for identifiers | Critical quoting difference |
| 7 | `CREATE SEMANTIC VIEW` (SQL DDL) | `CREATE VIEW ... WITH METRICS LANGUAGE YAML` | YAML-embedded DDL |
| 8 | `AI_SQL_GENERATION(...)` | No equivalent | Measures must be formal YAML expressions |
| 9 | `WITH SYNONYMS ('a', 'b')` in DDL | `synonyms:` list in YAML | Different syntax, same purpose |
| 10 | `PRIVATE` on facts/metrics | Not supported | Cannot hide intermediates in Databricks |

---

## 7. Category C Propagation Rules

A measure is Category C (requires window measures in YAML) if:

1. Its DAX expression directly contains time intelligence functions:
   `SAMEPERIODLASTYEAR`, `DATEADD`, `PARALLELPERIOD`, `DATESYTD/QTD/MTD`,
   `TOTALYTD/QTD/MTD`, `LASTDATE`, `FIRSTDATE`, `PREVIOUSYEAR`, `NEXTYEAR`
2. **OR** its DAX expression references another measure that is Category C
3. **OR** it uses INDEX-based filtering on a date table

**Decision rule:** If ANY measure in the arithmetic chain is Category C, the
whole measure is Category C.

**Example (correct YAML v1.1 syntax):**

```yaml
fields:
  - name: order_date
    expr: o_orderdate
  - name: fiscal_year
    expr: YEAR(o_orderdate)

measures:
  # Category A — simple aggregate
  - name: total_revenue
    expr: SUM(o_totalprice)

  # Category C — window measure for prior year
  - name: total_revenue_py
    expr: SUM(o_totalprice)
    window:
      - order: fiscal_year    # MUST be a named field, NOT source column
        range: current
        semiadditive: last
        offset: -1 year

  # Category C — composed, but references a Cat C measure
  - name: revenue_yoy_change
    expr: MEASURE(total_revenue) - MEASURE(total_revenue_py)
```

---

## 8. XMLA Components NOT Directly Mapped

| # | Component | Disposition |
|---|-----------|-------------|
| 1 | `dataSources[]` | Not needed — replaced by `source:` in YAML |
| 2 | `partitions[]` | Not needed — Databricks handles storage |
| 3 | `annotations[]` (PBI_Id, LinkedQueryName) | Skip or add to YAML comment if meaningful |
| 4 | `columns[].formatString` | Document in measure `description:` |
| 5 | `measures[].formatString` | Document in measure `description:` or `format:` block |
| 6 | `columns[].sortByColumn` | Document in field `description:` |
| 7 | `columns[].dataCategory` | Add to `description:` |
| 8 | `columns[].variations[]` | Skip — PBI auto-date hierarchy artifact |
| 9 | `columns[].isDefaultLabel` | Add to `description:` if meaningful |
| 10 | `columns[].isDefaultImage` | Skip — binary/image not supported |
| 11 | `measures[].kpi` | Document thresholds in measure `description:` |
| 12 | `hierarchies[]` | Model each level as a separate field |
| 13 | `tables[].isHidden: true` | Include table; note in YAML comment |
| 14 | `columns[].isHidden: true` | Include if needed by joins/measures; note in comment |
| 15 | `roles[]` | Not mapped — Databricks uses its own RBAC (RLS/column masks) |
| 16 | `perspectives[]` | Not mapped — use separate metric views per perspective if needed |
| 17 | `cultures[]` / translations | Not mapped — document locale-specific labels in `synonyms:` |

---

## 9. Pre-Submission YAML Checklist

Before running `CREATE OR REPLACE VIEW` or `ALTER VIEW`, verify:

1. Every measure uses an aggregate function or MEASURE() composition
2. No forward references — measures appear after their dependencies
3. No circular references between measures
4. `'on':` keys are quoted in all join blocks
5. All field names and measure names are unique across the entire view
6. Window measure `order:` references named fields, not source columns
7. No IFF(), DIV0(), or other Snowflake-only functions
8. Column names with special characters use backtick quoting
9. STRING columns that need aggregation have explicit CAST in `expr:`
10. `source:` references exactly one table (or joins block is used)
11. DAX traceability comments are present on every measure (`-- DAX:`)
12. `synonyms:` entries present for Genie discoverability
13. YAML version is 1.1
14. No PRIVATE keywords (not supported in Databricks)
