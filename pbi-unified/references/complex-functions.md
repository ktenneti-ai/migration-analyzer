# Complex Function Handling (Category F)

Category F measures cannot be expressed as a single Metric View measure. They require
wrapper views, pre-aggregated tables, or consumer-side query patterns.

## When to Use This Guide

- Measures scored < 40 (MANUAL_PORT or UNSUPPORTED)
- Measures using RANKX, TOPN, CONCATENATEX, ALL-family ratio patterns
- Measures with nested row contexts (EARLIER/EARLIEST)
- Semi-additive measures (LASTNONBLANK, CLOSINGBALANCE*)
- Measures with virtual table iterators that can't be simplified

## Pattern 1: RANKX → Window Function in Wrapper View

**DAX**: `RANKX(ALL(Product), [Total Sales],, DESC, Dense)`

**Cannot be a measure** (window function). Implement as wrapper view:

```sql
CREATE OR REPLACE VIEW catalog.schema.wrapper_product_rank AS
SELECT
  product_name,
  MEASURE(`Total Sales`) AS total_sales,
  DENSE_RANK() OVER (ORDER BY MEASURE(`Total Sales`) DESC) AS sales_rank
FROM catalog.schema.sales_metrics
GROUP BY product_name;
```

## Pattern 2: TOPN → LIMIT in Wrapper View

**DAX**: `TOPN(10, Products, [Total Sales], DESC)`

```sql
CREATE OR REPLACE VIEW catalog.schema.wrapper_top_products AS
SELECT product_name, MEASURE(`Total Sales`) AS total_sales
FROM catalog.schema.sales_metrics
GROUP BY product_name
ORDER BY total_sales DESC
LIMIT 10;
```

## Pattern 3: CONCATENATEX → String Aggregation

**DAX**: `CONCATENATEX(DISTINCT(Products[Category]), Products[Category], ", ")`

```sql
-- Option A: COLLECT_LIST (unordered)
SELECT category_group, CONCAT_WS(', ', COLLECT_LIST(DISTINCT product_category)) AS categories
FROM catalog.schema.sales_metrics
GROUP BY category_group;

-- Option B: array_sort for ordering
SELECT category_group,
       CONCAT_WS(', ', ARRAY_SORT(COLLECT_SET(product_category))) AS categories
FROM catalog.schema.sales_metrics
GROUP BY category_group;
```

## Pattern 4: Percent-of-Total (ALL/REMOVEFILTERS)

**DAX**: `DIVIDE([Sales], CALCULATE([Sales], ALL(Product)))`

The ALL removes the Product filter to get the total denominator. In a Metric View,
measures are plain aggregates — the "remove filter" semantics require consumer-side logic:

**Option A: Consumer query with MEASURE()**
```sql
SELECT
  `Product Category`,
  MEASURE(`Sales`) AS category_sales,
  MEASURE(`Sales`) / SUM(MEASURE(`Sales`)) OVER () AS pct_of_total
FROM catalog.schema.sales_metrics
GROUP BY `Product Category`;
```

**Option B: Measure pair (numerator + denominator)**
Define two measures in the spec:
- `Sales`: `sum(source.net_amount)`
- `Total Sales`: `sum(source.net_amount)` (same expression)

The consumer query computes the ratio — GROUP BY controls which filter is removed.

## Pattern 5: Semi-Additive (LASTNONBLANK / CLOSINGBALANCE)

**DAX**: `CALCULATE(SUM([Balance]), LASTNONBLANK('Date'[Date], SUM([Balance])))`

Semi-additive measures show the last known value (e.g., account balance). They need a
snapshot pattern, not a running aggregate.

**Option A: Pre-aggregated snapshot table**
```sql
-- Materialize daily snapshots
CREATE TABLE catalog.schema.balance_snapshot AS
SELECT account_id, balance_date, balance_amount
FROM (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY account_id ORDER BY balance_date DESC
  ) AS rn
  FROM catalog.schema.raw_balances
)
WHERE rn = 1;
```

**Option B: Window function in wrapper view**
```sql
CREATE OR REPLACE VIEW catalog.schema.wrapper_latest_balance AS
SELECT
  account_id,
  LAST_VALUE(balance_amount IGNORE NULLS) OVER (
    PARTITION BY account_id ORDER BY balance_date
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  ) AS latest_balance
FROM catalog.schema.balance_facts;
```

## Pattern 6: Year-over-Year / Period Comparison

**DAX**: `[Sales] - CALCULATE([Sales], SAMEPERIODLASTYEAR('Date'[Date]))`

Requires an explicit date dimension with period-shifted keys:

```sql
-- Date dim must have: date_key_ly (same day last year)
CREATE OR REPLACE VIEW catalog.schema.wrapper_yoy AS
WITH by_period AS (
  SELECT
    date_order.fiscal_year,
    date_order.fiscal_quarter,
    MEASURE(`Sales`) AS sales
  FROM catalog.schema.sales_metrics
  GROUP BY date_order.fiscal_year, date_order.fiscal_quarter
)
SELECT
  cy.fiscal_year, cy.fiscal_quarter,
  cy.sales AS current_sales,
  py.sales AS prior_year_sales,
  try_divide(cy.sales - py.sales, py.sales) AS yoy_growth
FROM by_period cy
LEFT JOIN by_period py
  ON cy.fiscal_year = py.fiscal_year + 1
  AND cy.fiscal_quarter = py.fiscal_quarter;
```

## MEASURE() Nesting Limits

`MEASURE()` in consumer queries enables composability, but:
- `MEASURE()` cannot reference other `MEASURE()` calls in the same SELECT
- Complex compositions need CTEs or subqueries
- Window functions over `MEASURE()` are allowed in consumer queries
- Verify current nesting limits against Databricks docs (evolving feature)

## Decision Framework

| DAX Pattern | Recommendation |
|---|---|
| RANKX/TOPN | Wrapper view with window function |
| CONCATENATEX | Consumer query with COLLECT_LIST |
| ALL-family ratio | Consumer query with MEASURE() + OVER() |
| Semi-additive | Pre-aggregated snapshot table |
| Time intelligence | Date dim with period columns + wrapper view |
| EARLIER/nested context | Restructure as CTE or pre-aggregated table |
| RLS functions | Separate UC row filter deliverable |
