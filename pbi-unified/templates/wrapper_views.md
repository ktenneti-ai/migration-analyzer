# Wrapper View Templates (Category F Measures)

Category F measures (RANKX, TOPN, CONCATENATEX, Pct-of-Total, Moving Average, YoY Growth)
cannot be expressed as a single Metric View measure expression. These templates show how
to implement them as **companion wrapper views** that consume the Metric View via MEASURE().

## 1. TOPN (Top-N by a Measure)

```sql
-- PBI DAX: TOPN(10, Products, [TotalSales], DESC)
CREATE OR REPLACE VIEW catalog.schema.wrapper_top10_products AS
SELECT
  product_name,
  MEASURE(`Total Sales`) AS total_sales
FROM catalog.schema.sales_metrics
GROUP BY product_name
ORDER BY total_sales DESC
LIMIT 10;
```

## 2. RANKX (Ranking)

```sql
-- PBI DAX: RANKX(ALL(Products), [TotalSales],, DESC, Dense)
CREATE OR REPLACE VIEW catalog.schema.wrapper_product_rank AS
SELECT
  product_name,
  MEASURE(`Total Sales`) AS total_sales,
  DENSE_RANK() OVER (ORDER BY MEASURE(`Total Sales`) DESC) AS sales_rank
FROM catalog.schema.sales_metrics
GROUP BY product_name;
```

## 3. CONCATENATEX (String Aggregation)

```sql
-- PBI DAX: CONCATENATEX(Products, [ProductName], ", ", [ProductName], ASC)
CREATE OR REPLACE VIEW catalog.schema.wrapper_product_list AS
SELECT
  category_name,
  CONCAT_WS(', ', COLLECT_LIST(product_name)) AS product_list
FROM catalog.schema.sales_metrics
GROUP BY category_name;
-- Note: COLLECT_LIST does not guarantee order; for ordered concatenation
-- use array_sort(collect_list(...)) or a window-based approach.
```

## 4. Percent of Total (ALL-family pattern)

```sql
-- PBI DAX: DIVIDE([Sales], CALCULATE([Sales], ALL(Products)))
-- Cannot be a single measure (ALL = remove filter = total denominator).
-- Implement as a consumer query using MEASURE():
SELECT
  product_category,
  MEASURE(`Sales`) AS category_sales,
  MEASURE(`Sales`) / SUM(MEASURE(`Sales`)) OVER () AS pct_of_total
FROM catalog.schema.sales_metrics
GROUP BY product_category;

-- Or as a wrapper view:
CREATE OR REPLACE VIEW catalog.schema.wrapper_sales_pct AS
SELECT
  product_category,
  MEASURE(`Sales`) AS sales,
  MEASURE(`Sales`) * 100.0 / SUM(MEASURE(`Sales`)) OVER () AS pct_of_total
FROM catalog.schema.sales_metrics
GROUP BY product_category;
```

## 5. Moving Average

```sql
-- PBI DAX: AVERAGEX(DATESINPERIOD(..., -3, MONTH), [Sales])
-- Requires explicit date dimension with period columns.
CREATE OR REPLACE VIEW catalog.schema.wrapper_sales_ma3m AS
SELECT
  order_month,
  MEASURE(`Sales`) AS monthly_sales,
  AVG(MEASURE(`Sales`)) OVER (
    ORDER BY order_month
    ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
  ) AS sales_ma_3m
FROM catalog.schema.sales_metrics
GROUP BY order_month;
```

## 6. Year-over-Year Growth

```sql
-- PBI DAX: DIVIDE([Sales] - CALCULATE([Sales], SAMEPERIODLASTYEAR('Date'[Date])), 
--                 CALCULATE([Sales], SAMEPERIODLASTYEAR('Date'[Date])))
-- Requires date dimension with a prior-year join or period column.
CREATE OR REPLACE VIEW catalog.schema.wrapper_yoy_growth AS
WITH current_year AS (
  SELECT
    d.fiscal_year,
    d.fiscal_quarter,
    MEASURE(`Sales`) AS sales
  FROM catalog.schema.sales_metrics
  GROUP BY d.fiscal_year, d.fiscal_quarter
)
SELECT
  cy.fiscal_year,
  cy.fiscal_quarter,
  cy.sales AS current_sales,
  py.sales AS prior_year_sales,
  try_divide(cy.sales - py.sales, py.sales) AS yoy_growth
FROM current_year cy
LEFT JOIN current_year py
  ON cy.fiscal_year = py.fiscal_year + 1
  AND cy.fiscal_quarter = py.fiscal_quarter;
```

## Usage Notes

- Wrapper views are **separate views** that SELECT FROM the Metric View using `MEASURE()`.
- They are NOT part of the Metric View YAML spec — they live alongside it.
- Each wrapper view can be consumed by Genie, dashboards, or notebooks independently.
- For Category F measures, the conversion report should list which wrapper template applies
  and the expected consumer query pattern.
- MEASURE() syntax: `MEASURE(\`Measure Name\`)` — backtick-quoted measure name.
