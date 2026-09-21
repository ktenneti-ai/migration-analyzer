# Unity Catalog Metric View — YAML Spec Reference (v1.1)

**Evolving feature.** Confirm the current YAML/DDL surface against Databricks docs at
implementation time and record the check date in `conversion_report.md`.

## YAML Structure

```yaml
version: 1.1
source: catalog.schema.fact_sales
filter: source.is_deleted = false        # optional base filter
joins:
  - name: product
    source: catalog.schema.dim_product
    on: source.product_id = product.product_id
    type: left                           # left (default) | inner
  - name: date_order
    source: catalog.schema.dim_date
    on: source.order_date = date_order.date_key
  - name: date_ship                      # role-playing: same table, different alias
    source: catalog.schema.dim_date
    on: source.ship_date = date_ship.date_key
dimensions:
  - name: Product Category
    expr: product.category
  - name: Order Date
    expr: date_order.calendar_date
  - name: Hierarchy L1 (Category)
    expr: product.category
measures:
  - name: Total Revenue
    expr: >-
      -- DAX: SUM(Sales[NetAmount])
      sum(source.net_amount)
  - name: Order Count
    expr: >-
      -- DAX: COUNTROWS(Sales)
      count(*)
  - name: Avg Order Value
    expr: >-
      -- DAX: DIVIDE([Total Revenue], [Order Count])
      try_divide(sum(source.net_amount), count(*))
```

## DDL Wrapper

### CREATE (first deployment)
```sql
CREATE OR REPLACE VIEW catalog.schema.sales_metrics
WITH METRICS
LANGUAGE YAML
COMMENT 'Converted from PBI model SalesModel rev 1'
AS $$
<yaml spec>
$$;
```

### ALTER (subsequent updates — preserves grants)
```sql
ALTER VIEW catalog.schema.sales_metrics AS $$
<yaml spec>
$$;
```

**ALTER VIEW IS supported and preferred** — it preserves existing grants. CREATE OR REPLACE
drops grants and recreates them. Use ALTER for updates after initial deployment.

## Querying

```sql
-- Basic: select dimensions and measures
SELECT `Product Category`, MEASURE(`Total Revenue`)
FROM catalog.schema.sales_metrics
GROUP BY ALL;

-- Multiple measures
SELECT
  `Product Category`,
  MEASURE(`Total Revenue`) AS revenue,
  MEASURE(`Order Count`) AS orders,
  MEASURE(`Avg Order Value`) AS aov
FROM catalog.schema.sales_metrics
GROUP BY ALL;

-- Filtering
SELECT `Product Category`, MEASURE(`Total Revenue`)
FROM catalog.schema.sales_metrics
WHERE `Order Date` >= '2024-01-01'
GROUP BY ALL;

-- Composability: MEASURE() in expressions
SELECT
  `Product Category`,
  MEASURE(`Total Revenue`) / SUM(MEASURE(`Total Revenue`)) OVER () AS pct_of_total
FROM catalog.schema.sales_metrics
GROUP BY ALL;
```

## Key Constraints

### Measures
- **Plain aggregates only**: no window functions, no subqueries, no correlated references
- Window/ratio logic belongs in the consumer query using `MEASURE()`
- `expr` must reference named fields (dimensions/join aliases defined in the spec)
- Original DAX must appear as `-- DAX: <expr>` comment above the SQL

### Joins
- One join per dimension table — never flatten multi-table joins
- Join keys must exist in the physical tables with compatible types
- No casts or functions in `on:` predicates (fix types upstream)
- Dimension-side key must be unique (fanout silently inflates measures)

### Dimensions
- Reference format: `alias.column_name` where alias is from `joins[].name` or `source`
- Hierarchy levels → individual dimensions with descriptive names
- Calculated dimensions can use `expr:` with functions (e.g., `to_date(source.date_str)`)

### Window Properties (for measures that support them)

```yaml
measures:
  - name: Revenue YTD
    expr: sum(source.net_amount)
    window:
      order: Order Date           # MUST reference a named dimension
      frame:
        type: rows               # rows | range
        start: unbounded preceding
        end: current row
      trailing: 1 year
      trailing_exclude: true     # exclude the anchor row
      leading: 0
      leading_exclude: false
```

**Critical**: Window `order:` must reference **named dimensions** (not raw column names).
Using a raw column that isn't defined as a dimension causes a silent failure.

**trailing/leading exclude**: `true` means the anchor row is excluded from the window.
This differs from typical SQL ROWS BETWEEN semantics where CURRENT ROW is always included.

### Format Properties

```yaml
measures:
  - name: Total Revenue
    expr: sum(source.net_amount)
    format:
      type: number
      decimal_places: 2
      prefix: "$"
```

### Parameters (if supported in current version)

```yaml
parameters:
  - name: start_date
    type: date
    default: "2024-01-01"
```

## Version History

| Version | Changes |
|---------|---------|
| 0.1 | Initial spec (outdated — do not use) |
| 1.1 | Current: window properties, format block, filter, join type |

## Mapping from PBI

| Power BI Concept | Metric View Equivalent |
|---|---|
| Fact table | `source:` |
| Dimension table + active 1:* relationship | `joins[]` entry |
| Inactive relationship (USERELATIONSHIP) | Additional named join alias |
| Column / hierarchy level | `dimensions[].expr` |
| Measure (translated DAX) | `measures[].expr` with `-- DAX:` |
| Model/table descriptions | `comment` in DDL, comments in expr |
| Display folder | `-- FOLDER:` comment in expr |
| Format string | `format:` block (if supported) |

## Join Semantics

PBI relationships behave like LEFT joins (blank row for unmatched keys). Metric View
default is also LEFT. A mismatch shows up as row-count parity diffs when the dimension
has orphan keys. Verify join type matches PBI behavior.
