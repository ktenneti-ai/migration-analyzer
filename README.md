# Power BI / Teradata → Databricks Migration Analyzer

Reverse-engineers Power BI + Teradata architectures and generates a migration
blueprint for moving the workload to Databricks. See the full application
scope and long-term design in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

This repository currently implements **Milestone 1**.

## What Milestone 1 does

- Create a migration project and upload one or more **`.json`** files
  (drag-and-drop or file picker).
- Detects whether a JSON file is a Power BI semantic-model export, a
  Teradata export, a Databricks export, or an unrecognized shape — without
  rejecting unfamiliar shapes.
- For Power BI semantic-model JSON: extracts tables, columns, measures, and
  relationships into a canonical metadata model.
- Parses each measure's DAX expression (bracket-based reference extraction)
  to build measure → measure and measure → column dependencies, computes
  dependency depth, and flags unresolved references as migration gaps.
- Builds a lineage graph (semantic model → table → column/measure, plus
  measure dependency edges and table-to-table relationship edges).
- Every extracted/derived fact carries a `status`
  (`CONFIRMED` / `INFERRED` / `REQUIRES_INPUT`) and a `provenance` record
  (source file, JSON path) — nothing is fabricated.
- UI: Dashboard (calculated counts), Power BI Tables/Measures/Relationships
  inventories, and an interactive Lineage Explorer (React Flow: zoom, pan,
  search, click-to-inspect).
- **Assessment Report**: a Migration Blueprint Document (spec section 13)
  built from whatever's actually been ingested — Power BI inventory, DAX
  analysis, cross-model shared-table detection, migration gaps are real;
  everything that needs Teradata/Databricks ingestion or an engine that
  doesn't exist yet is shown as an explicit `REQUIRES_INPUT` placeholder
  naming what's missing, never fabricated. Exportable as PDF or Word.
- **Migration Plan**: the nine fixed migration phases from spec section 26,
  with each phase's status computed from what's actually been ingested
  (Phase 1 "Discovery" turns `CONFIRMED` once Power BI data exists; every
  later phase stays `REQUIRES_INPUT` with a reason until Teradata/Databricks
  ingestion exists).
- **SQL Conversion** and **Databricks / Metric View** pages: the response
  shapes spec sections 18–20 describe are wired up end-to-end now, so the
  frontend won't need to change once Teradata SQL ingestion and the
  Gold-layer design engine are built; until then both report "pending" with
  a reason instead of showing fabricated data.

## What's deliberately deferred to later milestones

PBIX/PBIT/PBIP/TMDL/SQL/CSV/Excel ingestion, Teradata and Databricks
extraction, a real DAX/M/SQL AST, Bronze/Silver/Gold design recommendations,
actual SQL conversion, complexity classification, the validation framework,
and CSV/Excel export. The package layout already reserves a place for each
of these (see the `README.md` stub in each empty package under
`backend/app/`).

## Running it

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest                          # run the test suite
uvicorn app.main:app --reload   # serve the API on http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install
npm test        # run the component test suite (vitest)
npm run dev     # serve the UI on http://localhost:5180 (proxies /api to :8000)
```

Open the frontend URL, create a project on the **Projects** page, and
drag in `sample_data/finance_model.json` (or `operations_model.json`) to see
the Dashboard, Power BI inventories, and Lineage Explorer populate.

## Sample data

- `sample_data/finance_model.json` — a Power BI semantic model with measure
  dependency chains, including one deliberately unresolved reference (to
  exercise the migration-gap detection).
- `sample_data/operations_model.json` — a second model, for exercising
  multi-file project ingestion.
- `sample_data/teradata_sample.json` — a Teradata export shape, to exercise
  schema detection (Milestone 1 records it but does not yet extract it).
