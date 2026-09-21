# Genie Agent Configuration

After deploying the Metric View, configure a Genie Agent for natural-language querying.
This is optional Step 9 of the conversion pipeline.

## 4-Step Setup

### Step 1: Knowledge Store

Create a knowledge store document that describes the Metric View's business context:

```
Model: <model_name>
Description: <business description>
Primary fact: <fact table description>
Dimensions: <list of key dimensions and what they represent>
Measures: <list of measures with business definitions>
Common questions this answers:
  - "What is total revenue by product category?"
  - "How many orders were placed last month?"
  - "What is the average order value by region?"
```

Upload this as a knowledge store entry in the Genie Agent configuration.

### Step 2: Instructions

Configure the agent's system instructions:

```
You answer business questions about <domain> using the <view_name> Metric View.

Key measures:
- Total Revenue: sum of net sales amounts
- Order Count: number of distinct orders
- Avg Order Value: revenue divided by order count

When asked about time periods:
- "Last quarter" → filter on date dimension with appropriate range
- "YTD" → use the is_current_ytd dimension filter

NULL handling:
- NULL in a measure means no data exists for that slice (not zero)
- When comparing periods, NULL means the prior period had no data

Precision:
- Currency measures are decimal(19,4) — do not round prematurely
- Percentages should be displayed to 1 decimal place
```

### Step 3: Verified Answers

Add verified question-answer pairs for common queries:

```
Q: What is total revenue?
A: SELECT MEASURE(`Total Revenue`) FROM catalog.schema.sales_metrics;

Q: What is revenue by product category?
A: SELECT `Product Category`, MEASURE(`Total Revenue`)
   FROM catalog.schema.sales_metrics
   GROUP BY ALL
   ORDER BY MEASURE(`Total Revenue`) DESC;

Q: What are the top 10 products by revenue?
A: SELECT `Product Name`, MEASURE(`Total Revenue`) AS revenue
   FROM catalog.schema.sales_metrics
   GROUP BY `Product Name`
   ORDER BY revenue DESC
   LIMIT 10;
```

### Step 4: Hard Limits

Configure guardrails:

- **Allowed tables**: Only the Metric View and its companion wrapper views
- **Max rows**: 10,000 (prevent full-table scans in responses)
- **Timeout**: 30 seconds
- **Denied operations**: No DDL, no DML, no DESCRIBE, no SHOW — read-only SELECT only

## Grounding Surface

The Genie Agent's natural-language understanding depends on metadata:

1. **Measure comments**: The `-- DESC:` and `-- FOLDER:` comments in measure expressions
   are the primary grounding surface. Ensure every measure's PBI description is carried forward.

2. **Business synonyms**: Document alternative names for measures and dimensions:
   - "revenue" = "Total Revenue" = "Net Sales"
   - "orders" = "Order Count" = "number of orders"

3. **Time patterns**: Map natural-language time phrases to the correct query patterns:
   - "last quarter" → `WHERE date_dim.fiscal_quarter = <prior quarter>`
   - "year to date" → `WHERE date_dim.is_current_ytd = true`
   - "vs last year" → use the YoY wrapper view or period-shifted measures

4. **Edge cases**: Note in measure comments where results might surprise users:
   - "NULL means no data, not zero"
   - "Currency values are precise to 4 decimal places"
   - "Some measures exclude cancelled orders by default"

## Companion Wrapper Views

Genie can query wrapper views (from `templates/wrapper_views.md`) for Category F patterns:
- Top-N queries → `wrapper_top10_*` views
- Rankings → `wrapper_*_rank` views
- String aggregations → `wrapper_*_list` views
- YoY comparisons → `wrapper_yoy_*` views

Add these to the agent's allowed tables if deployed.
