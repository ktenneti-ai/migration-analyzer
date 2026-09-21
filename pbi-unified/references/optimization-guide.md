# Optimization Guide

Performance and quality optimizations for the generated Metric View or SQL objects.
Read this BEFORE drafting the spec — several optimizations change what SQL you emit.

## 1. Pre-aggregation for Iterator Measures

Measures flagged `iterator_over_virtual_table` (SUMX(FILTER(...), ...), etc.) translate
to correlated/window logic that cannot live inside a Metric View measure. Pre-aggregate
the virtual table as a Delta table or materialized view, then reference it as a source
or join in the spec.

**Action**: Create a pre-aggregated table, add it to `table_map.json`, reference it
in the translated SQL.

## 2. Date Dimension Preparation

Any model with time-intelligence measures (Category C) requires an explicit date dimension
with period-specific columns:

```sql
CREATE TABLE IF NOT EXISTS catalog.schema.dim_date AS
SELECT
  date_key,
  calendar_date,
  fiscal_year, fiscal_quarter, fiscal_month,
  is_current_ytd, is_current_qtd, is_current_mtd,
  date_key_ly,  -- same day last year
  date_key_lq,  -- same day last quarter
  date_key_lm   -- same day last month
FROM (
  SELECT
    CAST(FORMAT_NUMBER(UNIX_DATE(d), 0) AS INT) AS date_key,
    d AS calendar_date,
    YEAR(d) AS fiscal_year,
    QUARTER(d) AS fiscal_quarter,
    MONTH(d) AS fiscal_month,
    d BETWEEN DATE_TRUNC('year', CURRENT_DATE()) AND CURRENT_DATE() AS is_current_ytd,
    d BETWEEN DATE_TRUNC('quarter', CURRENT_DATE()) AND CURRENT_DATE() AS is_current_qtd,
    d BETWEEN DATE_TRUNC('month', CURRENT_DATE()) AND CURRENT_DATE() AS is_current_mtd,
    DATE_SUB(d, 365) AS date_key_ly,
    ADD_MONTHS(d, -3) AS date_key_lq,
    ADD_MONTHS(d, -1) AS date_key_lm
  FROM (SELECT EXPLODE(SEQUENCE(DATE'2020-01-01', DATE'2030-12-31', INTERVAL 1 DAY)) AS d)
);
```

## 3. Liquid Clustering

For fact tables with high cardinality, add liquid clustering on the primary date key
and the most-used filter dimension:

```sql
ALTER TABLE catalog.schema.fact_sales CLUSTER BY (order_date, product_category);
```

## 4. Join Predicate Optimization (D1)

Casts in join predicates prevent predicate pushdown and partition pruning:
- **Bad**: `ON CAST(f.date_key AS DATE) = d.calendar_date`
- **Good**: Ensure both sides have compatible types at source. Fix the upstream table
  or add a computed column.

## 5. Wide Dimension Pruning (D2)

If a dimension table has > 30 columns but only 5–10 are used in the spec, consider:
- Creating a dimension view that selects only the needed columns
- This reduces shuffle data in joins

## 6. Materialized View Candidates

Consider materializing views that:
- Are queried frequently (> 10x/day)
- Have stable underlying data (batch-loaded, not streaming)
- Contain expensive aggregations or many joins

```sql
CREATE MATERIALIZED VIEW catalog.schema.mv_daily_sales AS
SELECT order_date, product_category, SUM(amount) AS total_sales, COUNT(*) AS order_count
FROM catalog.schema.fact_sales
GROUP BY order_date, product_category;
```

Materialized views auto-refresh on the underlying table changes.

## 7. Semi-additive Measure Patterns (Category E)

Semi-additive measures (LASTNONBLANK, CLOSINGBALANCEYEAR) need a snapshot or window pattern:

```sql
-- LASTNONBLANK(dim_date, [Balance])
-- Pattern: get the last non-null value per entity per period
LAST_VALUE(balance IGNORE NULLS) OVER (
  PARTITION BY account_id
  ORDER BY calendar_date
  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
)
```

**This CANNOT be a Metric View measure** (window function). Implement as:
- A pre-aggregated snapshot table, or
- A companion wrapper view

## 8. Partition Pruning

Ensure the fact table is partitioned on the primary date column for efficient time-range queries:

```sql
-- Check existing partitioning
DESCRIBE DETAIL catalog.schema.fact_sales;

-- If not partitioned, consider:
-- ALTER TABLE catalog.schema.fact_sales SET TBLPROPERTIES ('delta.autoOptimize.optimizeWrite' = 'true');
```

## 9. Ratio-of-Total Measures (D5)

ALL-family measures (CALCULATE with ALL/REMOVEFILTERS) compute totals for ratio denominators.
In a Metric View, implement as a measure pair + consumer query:

```sql
-- Metric View has two measures:
-- 1. sales: sum(source.amount)
-- 2. total_sales: sum(source.amount)  -- same expression

-- Consumer query computes the ratio:
SELECT
  product_category,
  MEASURE(`sales`) AS category_sales,
  MEASURE(`sales`) / MEASURE(`total_sales`) AS pct_of_total
FROM catalog.schema.sales_metrics
GROUP BY product_category;
-- GROUP BY removes the product_category filter from total_sales
```

## 10. Duplicate Subexpression Extraction (D6)

If multiple measures share the same subexpression, extract it as a dedicated measure:

```sql
-- Before: Revenue = sum(qty * price), Avg Revenue = avg(qty * price)
-- After: add line_total dimension or shared measure
```

## 11. Statistics Collection

After creating/refreshing tables, compute statistics for the query optimizer:

```sql
ANALYZE TABLE catalog.schema.fact_sales COMPUTE STATISTICS FOR ALL COLUMNS;
ANALYZE TABLE catalog.schema.dim_product COMPUTE STATISTICS FOR ALL COLUMNS;
```

## 12. Genie Natural-Language Grounding (D8)

Metric View `comment:` and synonym metadata is the Genie grounding surface:
- Carry PBI `description` / `displayFolder` / `formatString` into SQL comments
- Document business synonyms for ambiguous names
- Map time-pattern phrasing ("last quarter", "YTD") to period-shifted measures
- Note edge cases (BLANK/NULL, currency rounding) in measure comments
