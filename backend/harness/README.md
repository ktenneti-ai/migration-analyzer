# Real-model accuracy harness

Runs real Power BI semantic models through the analyzer — the same
ingestion path the upload endpoint uses, then every downstream generator —
and checks the output against an **independent** parse of the same files
(`truth.py`, `dax_refs.py`, which share no code with `app/`). Where the two
disagree, that's a finding.

## Run it

```bash
cd backend && source .venv/bin/activate
mkdir -p ../real_models        # gitignored; put models here
python -m harness              # or: python -m harness /path/to/models
```

Writes `harness_reports/<timestamp>/report.md` and `results.json` (both
gitignored). Useful options:

| Option | |
|---|---|
| `--redact` | salted-hash every model/table/measure name and drop DAX, so the report can be shared |
| `--jobs N` | models analyzed in parallel |
| `--timeout SEC` | per model (default 180); a hung model is killed and reported |
| `--match TEXT` / `--limit N` | analyze a subset |

## What to put in `real_models/`

Any mix, searched recursively:

- **PBIP projects** (`X.SemanticModel/definition/*.tmdl`): best source. In
  Power BI Desktop, *File → Save as → Power BI project*, with the TMDL
  format preview enabled. The harness concatenates the folder into one
  upload, since the app accepts one file.
- **`model.bim`**: from an older PBIP, Tabular Editor, or SSMS/XMLA.
- **`.pbit`**: *File → Export → Power BI template*; its embedded model
  schema is extracted.
- **`.json` / `.tmdl`** files.
- `.pbix` files are listed as skipped: their model is compressed in a
  format only Power BI can read. Export them as `.pbit` or PBIP.

## What it checks

| Area | Check |
|---|---|
| Robustness | ingestion crash, rejection, unrecognized format, timeout, crash in any downstream stage (SQL translation, Gold design, Metric View, wrapper views, dashboard, plan, report, PDF/DOCX export) |
| Extraction | tables, columns, measures, relationships: missing or extra, compared by name |
| Fidelity | measure DAX dropped or altered; relationship M2M, bi-di and active flags |
| Lineage | measure → measure and measure → column edges the graph misses; Teradata sources not captured |
| Gaps | each "unresolved reference" gap is checked: real, or false (case mismatch, other-table column in row context, virtual column, text inside a comment or string) |
| SQL | `auto` / `auto_spot_check` translations that don't parse as Databricks SQL, leftover DAX, or known DAX-vs-SQL semantic differences (`&`, `\|\|`, `INT`, `LOG`, `WEEKDAY`, `TRIM`, 2-arg `MIN`/`MAX`); Metric View YAML and wrapper-view SQL validity |
| Coverage | model features the analyzer doesn't model at all (calculation groups, RLS/OLS, perspectives, incremental refresh, field parameters, ...), data-source mix, and DAX functions the classifier has no rule for |

## Reading the results

- Start with the **scorecard**: it's corpus-wide recall and correctness.
- **critical / high** findings mean wrong or missing output that a user
  would trust; **medium** means degraded accuracy; `unresolved_in_source`
  (info) means the harness couldn't resolve the reference either.
- The harness can be wrong too. If a finding looks like the harness's
  mistake rather than the analyzer's, fix `truth.py` / `dax_refs.py` and
  add a case to `tests/test_harness.py`.
- `tests/fixtures/real_shapes/` holds small, synthetic models written in
  the real export formats. Add a fixture there whenever a real model
  exposes a new shape.
