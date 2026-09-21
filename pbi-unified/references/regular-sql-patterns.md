# Mode B — Regular SQL Gold Schema Patterns

Mode B converts the PBI semantic model into a traditional gold-layer schema using
Delta tables, views, materialized views, and computed gold views. Use when the
Metric View surface is not available or when consumers need a conventional schema.

## Naming Conventions

| Object Type | Prefix | Example |
|---|---|---|
| Fact table (landed/cleansed) | `fact_` | `fact_sales` |
| Dimension table | `dim_` | `dim_product` |
| Standard view | `vw_` | `vw_sales_by_product` |
| Materialized view | `mv_` | `mv_daily_revenue` |
| Gold wide view (star join) | `gold_` | `gold_sales` |
| PBI measure wrapper | `pbi_` | `pbi_total_revenue` |

All identifiers in snake_case. PBI PascalCase names → snake_case via `snake()`.

## Conversion Pipeline (Mode B)

Steps 0–4 (extract → inventory → profile → classify → translate) are shared with
Mode A. Mode B diverges at Step 5 (build_view.py `--mode-b`).

Output files (numbered for execution order):

```
01_dimensions.sql        — dim_* tables (CTAS or CREATE TABLE + COPY)
02_facts.sql             — fact_* tables
03_star_join_view.sql    — gold_* wide view joining fact + dims
04_measure_views.sql     — pbi_* views (one per measure group)
05_materialized_views.sql — mv_* (candidates from optimization)
06_gold_wide.sql         — gold_* with all measures pre-joined
```

## Dimension Tables

```sql
CREATE TABLE IF NOT EXISTS catalog.schema.dim_product
USING DELTA
TBLPROPERTIES (
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.autoOptimize.autoCompact'   = 'true'
)
COMMENT 'PBI: DimProduct → dim_product'
AS
SELECT
  product_id,            -- PK (verify uniqueness)
  product_name,
  category,
  subcategory,
  brand
FROM catalog.schema.source_product;

-- Liquid clustering (preferred over Z-ORDER for new tables)
ALTER TABLE catalog.schema.dim_product
CLUSTER BY (category, subcategory);
```

### Dimension DDL Rules

- Use `CREATE TABLE ... AS SELECT` (CTAS) for initial materialization
- Include surrogate or natural PK — always verify uniqueness
- `TBLPROPERTIES`: autoOptimize for write-heavy dims, liquid clustering for query filters
- `COMMENT` should reference the original PBI table name
- Do not partition dimension tables (they're small)

## Fact Tables

```sql
CREATE TABLE IF NOT EXISTS catalog.schema.fact_sales
USING DELTA
PARTITIONED BY (order_date_partition)
TBLPROPERTIES (
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.autoOptimize.autoCompact'   = 'true'
)
COMMENT 'PBI: FactSales → fact_sales'
AS
SELECT
  order_id,
  product_id,          -- FK → dim_product.product_id
  customer_id,         -- FK → dim_customer.customer_id
  order_date,
  date_format(order_date, 'yyyy-MM') AS order_date_partition,
  quantity,
  net_amount,
  discount_amount,
  tax_amount
FROM catalog.schema.source_sales;

-- Liquid clustering (on FK + date)
ALTER TABLE catalog.schema.fact_sales
CLUSTER BY (order_date, product_id);
```

### Fact DDL Rules

- Partition by month or year based on volume
- Liquid clustering on high-cardinality join keys + date
- `decimal(19,4)` for currency columns, never `double`
- Date columns must be `DATE` or `TIMESTAMP`, not `STRING`
- FK columns should match dimension PK types exactly

## Star Join View (Gold)

```sql
CREATE OR REPLACE VIEW catalog.schema.gold_sales AS
SELECT
  -- Facts
  f.order_id,
  f.order_date,
  f.quantity,
  f.net_amount,
  f.discount_amount,
  f.tax_amount,

  -- Dim: Product
  p.product_name,
  p.category         AS product_category,
  p.subcategory      AS product_subcategory,
  p.brand            AS product_brand,

  -- Dim: Customer
  c.customer_name,
  c.region           AS customer_region,
  c.segment          AS customer_segment,

  -- Dim: Date
  d.calendar_date,
  d.fiscal_year,
  d.fiscal_quarter,
  d.month_name

FROM catalog.schema.fact_sales f
LEFT JOIN catalog.schema.dim_product p
  ON f.product_id = p.product_id
LEFT JOIN catalog.schema.dim_customer c
  ON f.customer_id = c.customer_id
LEFT JOIN catalog.schema.dim_date d
  ON f.order_date = d.date_key;
```

### Star Join Rules

- LEFT JOIN everything (matches PBI default relationship behavior)
- Prefix dimension columns with alias for disambiguation
- Pruning: include only columns referenced by at least one PBI measure or hierarchy
- No aggregation in the star join view — it's a wide row-level view

## Measure Wrapper Views

Each translated measure becomes a `pbi_*` view. Group related measures.

```sql
-- Simple aggregations
CREATE OR REPLACE VIEW catalog.schema.pbi_total_revenue AS
SELECT
  -- DAX: SUM(Sales[NetAmount])
  sum(net_amount) AS total_revenue
FROM catalog.schema.gold_sales;

-- With dimension breakdowns
CREATE OR REPLACE VIEW catalog.schema.pbi_revenue_by_product AS
SELECT
  product_category,
  product_subcategory,
  -- DAX: SUM(Sales[NetAmount])
  sum(net_amount) AS total_revenue,
  -- DAX: COUNTROWS(Sales)
  count(*) AS order_count,
  -- DAX: DIVIDE([Total Revenue], [Order Count])
  try_divide(sum(net_amount), count(*)) AS avg_order_value
FROM catalog.schema.gold_sales
GROUP BY product_category, product_subcategory;
```

### Filtered Measures (CALCULATE)

```sql
-- DAX: CALCULATE(SUM(Sales[NetAmount]), Products[Category] = "Electronics")
CREATE OR REPLACE VIEW catalog.schema.pbi_electronics_revenue AS
SELECT
  sum(net_amount) FILTER (WHERE product_category = 'Electronics') AS electronics_revenue,
  sum(net_amount) AS total_revenue,
  try_divide(
    sum(net_amount) FILTER (WHERE product_category = 'Electronics'),
    sum(net_amount)
  ) AS electronics_pct
FROM catalog.schema.gold_sales;
```

## Materialized Views (MV)

Use for expensive aggregations that are queried frequently.

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS catalog.schema.mv_daily_revenue AS
SELECT
  order_date,
  product_category,
  sum(net_amount) AS total_revenue,
  count(*) AS order_count,
  try_divide(sum(net_amount), count(*)) AS avg_order_value
FROM catalog.schema.gold_sales
GROUP BY order_date, product_category;
```

### MV Criteria

Materialize when **all** of these hold:
- Aggregation is expensive (fact table > 10M rows)
- Query pattern is predictable (same GROUP BY dimensions)
- Freshness tolerance ≥ 15 minutes (MV refresh is async)
- Source tables are Delta (MVs require Delta or streaming sources)

Do **not** materialize:
- Simple pass-through views (no aggregation)
- One-off or ad-hoc queries
- Measures with highly dynamic filter patterns

## Time Intelligence Patterns

### YTD

```sql
CREATE OR REPLACE VIEW catalog.schema.pbi_revenue_ytd AS
SELECT
  d.fiscal_year,
  d.fiscal_quarter,
  d.calendar_date,
  sum(f.net_amount) AS revenue,
  sum(sum(f.net_amount)) OVER (
    PARTITION BY d.fiscal_year
    ORDER BY d.calendar_date
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  ) AS revenue_ytd
FROM catalog.schema.fact_sales f
JOIN catalog.schema.dim_date d ON f.order_date = d.date_key
GROUP BY d.fiscal_year, d.fiscal_quarter, d.calendar_date;
```

### Year-over-Year

```sql
CREATE OR REPLACE VIEW catalog.schema.pbi_revenue_yoy AS
WITH by_month AS (
  SELECT
    d.fiscal_year,
    d.month_number,
    sum(f.net_amount) AS revenue
  FROM catalog.schema.fact_sales f
  JOIN catalog.schema.dim_date d ON f.order_date = d.date_key
  GROUP BY d.fiscal_year, d.month_number
)
SELECT
  cy.fiscal_year,
  cy.month_number,
  cy.revenue AS current_year_revenue,
  py.revenue AS prior_year_revenue,
  try_divide(cy.revenue - py.revenue, py.revenue) AS yoy_growth
FROM by_month cy
LEFT JOIN by_month py
  ON cy.fiscal_year = py.fiscal_year + 1
  AND cy.month_number = py.month_number;
```

### Moving Average

```sql
CREATE OR REPLACE VIEW catalog.schema.pbi_revenue_ma AS
SELECT
  order_date,
  sum(net_amount) AS daily_revenue,
  avg(sum(net_amount)) OVER (
    ORDER BY order_date
    ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
  ) AS revenue_30d_ma
FROM catalog.schema.gold_sales
GROUP BY order_date;
```

## Semi-Additive Measures

Balance/inventory measures that show the last known value:

```sql
CREATE OR REPLACE VIEW catalog.schema.pbi_latest_balance AS
WITH ranked AS (
  SELECT
    account_id,
    balance_date,
    balance_amount,
    ROW_NUMBER() OVER (
      PARTITION BY account_id ORDER BY balance_date DESC
    ) AS rn
  FROM catalog.schema.fact_balances
)
SELECT account_id, balance_date, balance_amount
FROM ranked
WHERE rn = 1;
```

## Gold Wide View (All Measures)

Final deliverable: a single wide view with all translated measures.

```sql
CREATE OR REPLACE VIEW catalog.schema.gold_sales_measures AS
SELECT
  g.product_category,
  g.product_subcategory,
  g.customer_region,
  g.fiscal_year,
  g.fiscal_quarter,
  g.month_name,

  -- Revenue measures
  sum(g.net_amount)                               AS total_revenue,
  count(*)                                         AS order_count,
  try_divide(sum(g.net_amount), count(*))          AS avg_order_value,

  -- Filtered measures
  sum(g.net_amount) FILTER (WHERE g.product_category = 'Electronics')
                                                   AS electronics_revenue,

  -- Derived measures
  try_divide(
    sum(g.net_amount) FILTER (WHERE g.product_category = 'Electronics'),
    sum(g.net_amount)
  )                                                AS electronics_pct

FROM catalog.schema.gold_sales g
GROUP BY
  g.product_category, g.product_subcategory,
  g.customer_region,
  g.fiscal_year, g.fiscal_quarter, g.month_name;
```

## Deployment Order

1. Dimension tables (no dependencies)
2. Fact tables (may reference dimensions for FK validation)
3. Star join view (references facts + dims)
4. Measure wrapper views (reference star join)
5. Materialized views (reference star join or measure views)
6. Gold wide view (references star join)

Grant `SELECT` on views; restrict `INSERT/UPDATE/DELETE` to ETL principals only.

## Mode B vs Mode A — When to Choose

| Factor | Mode A (Metric View) | Mode B (Regular SQL) |
|---|---|---|
| Dynamic grain | Yes (MEASURE() + GROUP BY) | No (fixed per view) |
| Composability | MEASURE() nesting | Must pre-compute |
| Genie Agent support | Native | Requires verified answers |
| Window functions | In consumer queries | In view definitions |
| Materialization | Not applicable | Delta tables + MVs |
| BI tool compatibility | Databricks-native only | Any SQL client |
| Schema complexity | Single YAML + DDL | Multiple objects |
