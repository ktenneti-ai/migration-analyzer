# Model Coverage Matrix

PBI semantic models can use features beyond plain tables/relationships/measures. Each
feature has a handling rule, a severity level, and a disposition path.

## Feature Matrix

| Feature | Severity | Handling Rule | Disposition |
|---------|----------|---------------|-------------|
| **Calculation groups** | BLOCKER | Each calc item × base measure pair must be materialized as its own measure or dropped deliberately. Model-level -25 penalty. | Decide matrix with user before proceeding |
| **Bi-directional relationships** | HIGH | Filter path ambiguity — dimension-side join keys MUST be uniqueness-checked (fanout inflates measures silently). Cap affected measures at 45. | Redesign filter paths; consider separate views per filter direction |
| **Many-to-many (M:M) relationships** | HIGH | Requires bridge-table design. Cap affected measures at 45. Fanout risk is even higher than bi-di. | Design bridge table or dedicated aggregation views |
| **Row-Level Security (RLS)** | HIGH | `USERNAME()` / `USERPRINCIPALNAME()` / `CUSTOMDATA()` cap measures at 10 (UNSUPPORTED). RLS is never migrated implicitly into the Metric View. | Deliver as UC row filters / column masks — separate deliverable |
| **Inactive relationships** | MEDIUM | Often paired with `USERELATIONSHIP()` in measures. If USERELATIONSHIP is used, add a role-played join alias pointing to the same physical table with the alternate key. | Add role-playing join aliases in `table_map.json` |
| **Calculated tables** | MEDIUM | PBI calculated tables (DAX expressions that produce tables) must be materialized as Delta tables (CTAS). The DAX table expression is inventoried but NOT auto-translated. | Materialize as Delta, add to table_map.json |
| **Role-playing dimensions** | MEDIUM | Same physical table joined multiple times with different keys (e.g. dim_date joined as order_date and ship_date). | Add multiple join aliases in table_map.json's `role_playing` array |
| **Perspectives** | LOW | PBI perspectives are visibility filters, not security. UC has no direct equivalent. | Document in report; implement via view column selection if needed |
| **Cultures / Translations** | LOW | PBI localization metadata. No UC equivalent. | Document in report; consider UC column comments for aliases |
| **Composite mode / DirectQuery** | INFO | The extraction works regardless — model.json is the same shape. But DirectQuery sources may need different physical table mappings. | Note in profile; verify table_map physical names |
| **Aggregations (agg tables)** | INFO | PBI auto-aggregation tables are extraction artifacts. They should be excluded from the Metric View (the fact table at detail grain is the source). | Exclude from table_map; note in report |

## TMDL Fidelity Warning

When the source is a TMDL folder (`.tmdl` files from pbip), the extraction is best-effort:
- **Extracted**: table names, column names, measures (name + DAX), relationships
- **NOT extracted**: data types, calculated columns, hierarchies, RLS roles, calculation
  groups, perspectives, cultures, partition sources

If any of the above are critical to the conversion, re-export as `.bim` (Tabular Editor:
File → Save to file) for full fidelity. The extraction script warns when `tmdl_best_effort: true`.

## Decision Recording

Every HIGH/BLOCKER feature must have a recorded decision before the review gates pass (G5).
Record decisions in the conversion report's manual checklist:
- **Accepted**: user explicitly acknowledges the limitation
- **Resolved**: a specific technical solution was implemented
- **Deferred**: out of scope for this conversion; tracked separately
