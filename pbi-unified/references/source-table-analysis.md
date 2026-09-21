# Source Table Analysis — PBI Model vs Unity Catalog

**Source-first, always.** Never write a `joins:`/`dimensions:`/`measures:` entry against
a physical table or column you haven't verified exists — with a compatible type — in the
target catalog. `table_map.json` is a **confirmed** mapping, not a guess.

## 5-Phase Profiling Checklist

### Phase 1: Table Inventory
- [ ] List every PBI table from `model.json.tables[]`
- [ ] Identify its Unity Catalog equivalent (`profile_tables.py` proposes matches)
- [ ] Human confirms each match (or provides correct physical name)
- [ ] PBI tables with no match → BLOCKER (see `missing_tables.sql`)

### Phase 2: Column Reconciliation
- [ ] Map PBI display names → snake_case UC columns (PascalCase `OrderID` → `order_id`)
- [ ] Check data type compatibility per column (`profile.json` dtype_flags)
- [ ] Identify missing columns (PBI columns not in matched UC table)
- [ ] Identify columns needing backtick-quoting in Spark SQL

### Phase 3: Data Type Issues
- [ ] STRING/VARCHAR columns holding numeric data → need `try_cast(... as decimal/double)`
- [ ] STRING columns holding dates → need `to_date`/`to_timestamp`
- [ ] Currency columns → ensure `decimal(19,4)`, not `double`
- [ ] Boolean columns → confirm representation (true/false vs 1/0)

### Phase 4: Data Quality
- [ ] Row count per table (flag thin or partial data)
- [ ] Date range coverage (will time-intelligence measures have enough history?)
- [ ] NULL density on key columns (affects join behavior)
- [ ] Orphan foreign keys (dimension values not in dimension table → fanout risk)
- [ ] Document data gaps explicitly

### Phase 5: Join Key Validation
- [ ] Identify join keys between fact and dimension physical tables
- [ ] Confirm dimension-side key is unique (grain check)
- [ ] Check for compound keys (multi-column joins)
- [ ] Verify join key types match (no implicit casting needed)

## Getting a Catalog Scan

### With Live SQL Warehouse Connection

```sql
-- Tables + row counts
SELECT table_catalog, table_schema, table_name
FROM system.information_schema.tables
WHERE table_schema = '<schema>';

-- Columns + types
SELECT table_name, column_name, full_data_type
FROM system.information_schema.columns
WHERE table_schema = '<schema>'
ORDER BY table_name, ordinal_position;

-- Per table: row count and sample
SELECT count(*) AS row_count FROM <catalog>.<schema>.<table>;
SELECT * FROM <catalog>.<schema>.<table> LIMIT 20;

-- Orphan FK check (per join)
SELECT f.<fk_col>, COUNT(*) AS orphan_count
FROM <fact_table> f
LEFT JOIN <dim_table> d ON f.<fk_col> = d.<pk_col>
WHERE d.<pk_col> IS NULL
GROUP BY f.<fk_col>
HAVING COUNT(*) > 0;

-- Cardinality check (per dimension key)
SELECT '<dim_table>' AS tbl, '<pk_col>' AS col,
       COUNT(*) AS total_rows,
       COUNT(DISTINCT <pk_col>) AS distinct_keys,
       COUNT(*) - COUNT(DISTINCT <pk_col>) AS duplicate_keys
FROM <dim_table>;
```

### Catalog Scan JSON Format

Shape results into the `--catalog-scan` JSON that `profile_tables.py` expects:

```json
{"tables": [
  {"name": "catalog.schema.fact_sales", "row_count": 128341,
   "columns": [{"name": "order_id", "type": "bigint"},
               {"name": "net_amount", "type": "string"},
               {"name": "order_date", "type": "string"}],
   "sample": [{"net_amount": "123.45", "order_date": "2024-01-05"}]}
]}
```

### No Live Connection

Run `profile_tables.py` without `--catalog-scan` — it name-matches and marks every match
as **unverified**. Hand the user the SQL queries above to run manually. Never silently
assume a name match is correct.

## PBI → Spark Type Mapping

| PBI dataType | Spark SQL type | Notes |
|---|---|---|
| `int64` | `bigint` | |
| `double` | `double` | |
| `decimal` | `decimal(38,10)` | |
| `currency` | `decimal(19,4)` | Fixed 4dp — don't use double |
| `dateTime` | `timestamp` | |
| `date` | `date` | |
| `string` | `string` | |
| `boolean` | `boolean` | |
| `binary` | `binary` | |

## Gap Severity

| Gap | Severity | Impact |
|---|---|---|
| PBI table has no UC match | BLOCKER | Cannot join or aggregate |
| PBI column used by a measure missing from UC table | HIGH | Measure cannot translate |
| VARCHAR-numeric column feeding a measure without cast | MEDIUM | Silent wrong results |
| VARCHAR-numeric column only in dimensions | LOW | Wrong sort/filter behavior |
| String-date column without cast | MEDIUM | Date filters/time-intel broken |
| Row count far below DAX time window | MEDIUM | NULLs instead of zeros |
| Fuzzy name match only | LOW | Confirm by hand |

## Landing Missing Tables

`profile_tables.py` emits `missing_tables.sql` with starter CTAS templates. Confirm the
real catalog/schema and column semantics before running. After `CREATE TABLE`, land data with:
- `COPY INTO` for batch loads
- Auto Loader for continuous ingestion
- The PBI table's `source_hint` in `model.json` is the starting clue for the data source
