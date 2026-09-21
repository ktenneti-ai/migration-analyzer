# DAX → Spark SQL / Metric View Translation Catalog

Four tiers. The tier decides *how* a measure is translated and feeds the confidence
score (see `confidence-scoring.md`). Classification always comes from the parsed
function inventory + structural patterns — never from expression length.

## Tier 1 — Mechanical (safe to auto-translate)

### Aggregation Functions

| DAX | Spark SQL | Notes |
|---|---|---|
| `SUM(t[c])` | `sum(c)` | |
| `AVERAGE(t[c])` | `avg(c)` | |
| `MIN(t[c])` / `MAX(t[c])` | `min(c)` / `max(c)` | |
| `COUNTROWS(t)` | `count(*)` | Only when `t` is the view's source/fact |
| `COUNT(t[c])` / `COUNTA` | `count(c)` | COUNTA on non-numeric = `count(c)` |
| `DISTINCTCOUNT(t[c])` | `count(distinct c)` | |
| `DISTINCTCOUNTNOBLANK` | `count(distinct c)` | Spark `count distinct` already skips NULL |
| `DIVIDE(a,b)` | `try_divide(a,b)` | NULL on div-by-zero, matches DAX BLANK. **Not NULLIF.** |
| `DIVIDE(a,b,alt)` | `coalesce(try_divide(a,b), alt)` | |
| `BLANK()` | `NULL` | Comparison semantics differ — see BLANK note below |

### Scalar Math

| DAX | Spark SQL | Notes |
|---|---|---|
| `ABS(x)` | `abs(x)` | |
| `ROUND(x, n)` | `round(x, n)` | |
| `ROUNDUP(x, n)` | `ceil(x * power(10,n)) / power(10,n)` | Or approximate with `ceil()` |
| `ROUNDDOWN(x, n)` | `floor(x * power(10,n)) / power(10,n)` | Or approximate with `floor()` |
| `INT(x)` | `cast(x as int)` | DAX INT truncates toward zero |
| `MOD(a, b)` | `mod(a, b)` | |
| `SQRT(x)` | `sqrt(x)` | |
| `EXP(x)` | `exp(x)` | |
| `LN(x)` | `ln(x)` | |
| `LOG(x, base)` | `log(base, x)` | **Arg order reversed** |
| `LOG10(x)` | `log10(x)` | |
| `POWER(x, n)` | `power(x, n)` | |
| `PI()` | `pi()` | |
| `RAND()` | `rand()` | Non-deterministic — note in comments |
| `CURRENCY(x)` | `cast(x as decimal(19,4))` | |
| `CONVERT(x, type)` | `cast(x as <type>)` | Map DAX type to Spark type |

### String Functions

| DAX | Spark SQL | Notes |
|---|---|---|
| `CONCATENATE(a, b)` | `concat(a, b)` | DAX `&` operator also → concat |
| `COMBINEVALUES(sep, a, b, ...)` | `concat_ws(sep, a, b, ...)` | |
| `LEFT(s, n)` | `left(s, n)` | |
| `RIGHT(s, n)` | `right(s, n)` | |
| `MID(s, start, len)` | `substring(s, start, len)` | DAX is 1-based, Spark too |
| `LEN(s)` | `length(s)` | |
| `UPPER(s)` / `LOWER(s)` | `upper(s)` / `lower(s)` | |
| `TRIM(s)` | `trim(s)` | |
| `SUBSTITUTE(s, old, new)` | `replace(s, old, new)` | |
| `REPLACE(s, start, len, new)` | `overlay(s PLACING new FROM start FOR len)` | Different semantics from SUBSTITUTE |
| `SEARCH(find, within [,start])` | `locate(lower(find), lower(within) [,start])` | Case-insensitive; 0 if not found |
| `FIND(find, within [,start])` | `locate(find, within [,start])` | Case-sensitive |
| `EXACT(a, b)` | `(a = b)` with case-sensitive collation | Verify collation settings |
| `REPT(s, n)` | `repeat(s, n)` | |
| `UNICHAR(n)` | `char(n)` | |
| `UNICODE(s)` | `ascii(s)` | Approximate — only works for ASCII range |
| `FORMAT(x, fmt)` | See format mapping below | |
| `PATHITEM(path, n)` | `split(path, '\|')[n-1]` | DAX paths use `\|` delimiter |

### Date/Time Functions

| DAX | Spark SQL | Notes |
|---|---|---|
| `TODAY()` | `current_date()` | Timezone: Spark session TZ vs PBI service TZ |
| `NOW()` | `current_timestamp()` | |
| `YEAR(d)` | `year(d)` | |
| `MONTH(d)` | `month(d)` | |
| `DAY(d)` | `day(d)` | |
| `HOUR(t)` | `hour(t)` | |
| `MINUTE(t)` | `minute(t)` | |
| `SECOND(t)` | `second(t)` | |
| `WEEKDAY(d [,type])` | `dayofweek(d)` | Return value differs by type arg — check |
| `WEEKNUM(d [,type])` | `weekofyear(d)` | |
| `EOMONTH(d, months)` | `last_day(add_months(d, months))` | |
| `DATE(y, m, d)` | `make_date(y, m, d)` | |
| `DATEDIFF(d1, d2, interval)` | `datediff(d2, d1)` | **Arg order and interval differ** |
| `CALENDAR(start, end)` | `explode(sequence(start, end, interval 1 day))` | Table function — different context |
| `CALENDARAUTO()` | N/A | Auto date table — use explicit dim_date |

### Logical / Constants

| DAX | Spark SQL | Notes |
|---|---|---|
| `TRUE()` | `true` | |
| `FALSE()` | `false` | |
| `AND(a, b)` | `a AND b` | |
| `OR(a, b)` | `a OR b` | |
| `NOT(x)` | `NOT x` | |
| `IN {a, b, c}` | `IN (a, b, c)` | Curly braces → parens |

### FORMAT String Mapping

| DAX Format | Spark Function | Notes |
|---|---|---|
| `"#,##0"` | `format_number(x, 0)` | |
| `"#,##0.00"` | `format_number(x, 2)` | |
| `"0.0%"` | `concat(format_number(x * 100, 1), '%')` | DAX auto-multiplies by 100 |
| `"$#,##0.00"` | `concat('$', format_number(x, 2))` | |
| `"yyyy-MM-dd"` | `date_format(d, 'yyyy-MM-dd')` | |
| `"MMM yyyy"` | `date_format(d, 'MMM yyyy')` | |

## Tier 2 — Pattern Rewrites (auto-translate, spot-check)

### IF / SWITCH

- `IF(cond, a [, b])` → `CASE WHEN cond THEN a ELSE b END` (missing b → `ELSE NULL`)
- `SWITCH(TRUE(), c1, r1, c2, r2, …, else)` → searched `CASE WHEN c1 THEN r1 …`
- `SWITCH(expr, v1, r1, …)` → simple `CASE expr WHEN v1 THEN r1 …`

### ISBLANK / COALESCE

- `ISBLANK(x)` → `x IS NULL`
  - **Caution**: In DAX, `BLANK() = 0` is TRUE. If the measure compares blanks to
    zero/empty-string, port with `coalesce(x, 0)` and note in the translation comment.
- `COALESCE(a, b, ...)` → `coalesce(a, b, ...)` (identical)

### CALCULATE (simple case)

`CALCULATE(<agg>, <boolean filters>)` → `agg(expr) FILTER (WHERE <predicates>)`

Only when **every** filter argument is a plain boolean predicate on columns reachable in
the view's join graph, with **no** ALL/REMOVEFILTERS/KEEPFILTERS/USERELATIONSHIP/FILTER()
arguments. Multiple predicates AND together.

- `IN {a,b}` → `IN (a,b)`
- `<>` → `!=`
- `&&` → `AND`, `||` → `OR`
- DAX string literals `"text"` → SQL `'text'`

### Iterators (simple case)

`SUMX/AVERAGEX/MINX/MAXX/COUNTX(t, <expr>)` where `t` is a bare table → `sum(<expr>)` etc.

Valid only when `t` is the view's source grain. If `t` is a virtual table
(FILTER/VALUES/ADDCOLUMNS), downgrade to Tier 3.

### COUNTBLANK

`COUNTBLANK(t[c])` → `count(*) FILTER (WHERE c IS NULL)`

### SELECTEDVALUE

`SELECTEDVALUE(t[c] [, alt])` — context-dependent by design. Only portable when consumers
always group by that column. Downgrade to Tier 3.

## Tier 3 — Templated (candidate SQL, `-- REVIEW` marked)

### CALCULATE with FILTER() table arg
Rewrite predicate as FILTER-clause aggregate if row-level; otherwise CTE template.

### ALL / ALLEXCEPT / REMOVEFILTERS
Window template: `sum(x) OVER ()` or `PARTITION BY <kept cols>`.
**Cannot be a Metric View measure** — implement as measure pair + consumer MEASURE() query.

### Time Intelligence

`SAMEPERIODLASTYEAR`, `DATEADD`, `PARALLELPERIOD`, `DATESYTD/QTD/MTD`, `TOTALYTD/QTD/MTD`,
`DATESINPERIOD`, `DATESBETWEEN`, `PREVIOUSMONTH/QUARTER/YEAR`, `NEXTMONTH/QUARTER/YEAR`,
`FIRSTDATE`, `LASTDATE`, `STARTOFMONTH/QUARTER/YEAR`, `ENDOFMONTH/QUARTER/YEAR`

All require an **explicit date dimension** with period columns. Templates:
- **YTD**: `FILTER (WHERE d.is_current_ytd)` or date range predicate
- **Prior period**: self-join alias on date dim with shifted key (`d_ly.date_key = d.date_key_ly`)
- **Period range**: `FILTER (WHERE d.calendar_date BETWEEN ... AND ...)`

Always emit `-- REVIEW: time intelligence`, never silently port.

### RANKX / TOPN
Window function templates — cannot be Metric View measures. → Wrapper view.

### LOOKUPVALUE
Add explicit join in `joins:` block. Reference joined alias column.

### RELATED / RELATEDTABLE
Relationship traversal → reference joined alias column. RELATEDTABLE inside iterator → CTE.

### VAR/RETURN
Inline VARs into RETURN expression when scalar and side-effect-free. Otherwise decompose
into helper measures. No Spark SQL equivalent of DAX VAR.

### Measure References [Other Measure]
Substitute translated dependency (topological order). Score = min(self, deps).

## Tier 4 — Manual Port / Unsupported (stub only)

| Function | Why | Handling |
|---|---|---|
| USERELATIONSHIP | Rewires join graph per-measure | Role-played join alias or second view |
| TREATAS / CROSSFILTER | Virtual relationships | Redesign required |
| Semi-additive (LASTNONBLANK, etc.) | Snapshot/window pattern | Pre-aggregated table |
| EARLIER / EARLIEST | Nested row context | CTE/pre-agg restructure |
| USERNAME / USERPRINCIPALNAME / CUSTOMDATA | RLS-coupled | UC row filters (separate deliverable) |
| Unknown functions | No verified mapping | needs_review at best |

## Cross-cutting Rules

1. **Preserve original DAX** as `-- DAX: <expr>` above every translated expression
2. **Never mix return types** across CASE branches (DAX coerces; Spark errors)
3. **Currency** = DAX fixed 4dp → `decimal(19,4)`. Don't let sums run in `double`
4. **BLANK vs NULL**: `BLANK()+5 = BLANK` in DAX but `NULL+5 = NULL` in SQL — same. However,
   `BLANK() = 0` is TRUE in DAX but `NULL = 0` is NULL in SQL. Any measure relying on
   BLANK/zero equivalence needs explicit `coalesce(x, 0)` and a translation comment
5. **No `IFF()`** — Databricks uses `IF()` or `CASE WHEN`. `IFF()` is Snowflake-only
6. **Backtick quoting** for identifiers: `` `My Column` ``, not `[My Column]`
