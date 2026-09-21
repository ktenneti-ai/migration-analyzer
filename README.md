# Power BI / Teradata → Databricks Migration Analyzer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Reverse-engineers Power BI + Teradata architectures and generates a migration
blueprint for moving the workload to Databricks. See the full application
scope and long-term design in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

This repository currently implements **Milestone 1** (Power BI JSON and TMDL
ingestion, canonical metadata model, lineage graph), plus a recommendation
engine (DAX classification, Gold fact/dimension inference, SQL translation,
Metric View YAML, and wrapper-view generation) adapted from the
`pbi-unified` skill — see [`pbi-unified/`](pbi-unified/) for the source
material and `backend/app/recommendations/` + `backend/app/parsers/dax/` for
the ported logic.

Licensed under the [MIT License](LICENSE).

## Demo it locally (recommended)

This is the reliable way to run the app — two terminals, no cloud
dependency, no auth walls.

**1. Clone the repo:**

```bash
git clone https://github.com/ktenneti-ai/migration-analyzer.git
cd migration-analyzer
```

**2. Start the backend** (terminal 1):

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload   # serves the API on http://localhost:8000
```

**3. Start the frontend** (terminal 2, from the repo root):

```bash
cd frontend
npm install
npm run dev   # serves the UI on http://localhost:5180 (proxies /api to :8000)
```

**4. Open the app:** go to **http://localhost:5180** in your browser.

**5. Try it:** on the **Projects** page, create a project and upload one of
the sample files below (or your own Power BI `.json`/model.bim export or
`.tmdl` file). Then explore the **Dashboard**, **Power BI Inventory**,
**Relationship Inventory**, **Lineage Explorer**, **Teradata Assessment**,
**Migration Gaps**, and **Assessment Report** pages from the sidebar — every
number shown is computed live from whatever you just ingested.

To stop either server, `Ctrl+C` in its terminal.

## Running it in GitHub Codespaces

> **Known limitation:** in this repository's Codespaces environment, the
> frontend's forwarded port (5180) has an unresolved, intermittent
> GitHub tunnel-authentication issue — the underlying `/assets/*.js` request
> sometimes gets redirected to GitHub's sign-in flow or returns 401 even when
> the port is explicitly set to "public," which breaks the page for the
> browser regardless of which browser is used. The backend port (8000) is
> not affected. This isn't something in the app or `.devcontainer/` config —
> it's been root-caused to GitHub's tunnel-relay behavior for this
> environment, not something a code or config change here can reliably fix.
> **Use the local instructions above for a dependable demo.**

If you want to try Codespaces anyway: click **Code → Codespaces → Create
codespace on main**. It installs both the backend and frontend automatically
and starts both servers (the frontend is served from a production build via
`vite preview`, not the dev server). If the forwarded port doesn't load, open
the **Ports** tab and check that port 5180 is set to **Public** visibility;
if it still doesn't load, that's the known issue above.

If either server needs a restart (e.g. after `pip install`-ing something new),
re-run `bash .devcontainer/start.sh` in a terminal — it kills and relaunches
both. Logs are at `/tmp/migration-analyzer-logs/{backend,frontend,start}.log`.

## What Milestone 1 does

- Create a migration project and upload one or more **`.json`** (Power BI
  model.bim-style export) or **`.tmdl`** files (drag-and-drop or file
  picker).
- Detects whether a file is a Power BI semantic-model JSON export, TMDL, a
  Teradata export, a Databricks export, or an unrecognized shape — without
  rejecting unfamiliar shapes.
- Extracts tables, columns, measures, and relationships into a canonical
  metadata model regardless of which format it came from.
- Detects Power BI's Auto Date/Time system tables (GUID-suffixed calendar
  tables) and gives them a readable display name derived from what they're
  joined to, excluding them from counts to match what Power BI Desktop's own
  model view shows — while still exposing them (and the real object) on
  request.
- For TMDL: also reads each table's partition M query for a
  `Teradata.Database(...)` connector call, capturing the exact upstream
  Teradata database/schema/object per table (surfaced on the **Teradata
  Assessment** page and in the lineage graph as its own node), and
  classifies each as a view or base table via Teradata's "V_" naming
  convention.
- Parses each measure's DAX expression (bracket-based reference extraction)
  to build measure → measure and measure → column dependencies, computes
  dependency depth and a 0–100 migration-complexity score/category (adapted
  from the `pbi-unified` skill's classification methodology), and flags
  unresolved references — plus many-to-many and bi-directional
  relationships, which require a migration design decision — as migration
  gaps.
- Builds a lineage graph (Teradata source → semantic model's source file →
  table → column/measure, plus measure dependency edges and table-to-table
  relationship edges) with upstream/downstream tracing, search, and
  click-to-inspect detail.
- Every extracted/derived fact carries a `status`
  (`CONFIRMED` / `INFERRED` / `REQUIRES_INPUT`) and a `provenance` record
  (source file, JSON path) — nothing is fabricated.
- UI: Dashboard (calculated counts), Power BI Tables/Measures/Relationships
  inventories, Teradata Assessment, and an interactive Lineage Explorer
  (React Flow: zoom, pan, search, click-to-inspect).
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

PBIX/PBIT/PBIP/SQL/CSV/Excel ingestion, Teradata SQL/DDL ingestion (views and
base tables discovered directly from Teradata rather than referenced via
Power BI), a real DAX/M/SQL AST (the classifier/translator are regex-based,
not a full parser), the validation framework, and CSV/Excel export. Bridge
tables, aggregates, and confirmed fact grain also need Teradata source data
the app doesn't have yet. The package layout reserves a place for each of
these (see the `README.md` stub in each still-empty package under
`backend/app/`).

## Running the test suites

```bash
cd backend && source .venv/bin/activate && pytest      # backend tests
cd frontend && npm test                                 # frontend tests (vitest)
```

## Sample data

- `sample_data/finance_model.json` — a Power BI semantic model (JSON) with
  measure dependency chains, including one deliberately unresolved reference
  (to exercise the migration-gap detection).
- `sample_data/finance_model.tmdl` — the same shape as a TMDL export, to
  exercise the TMDL adapter.
- `sample_data/operations_model.json` — a second model, for exercising
  multi-file project ingestion.
- `sample_data/teradata_sample.json` — a Teradata export shape, to exercise
  schema detection (Milestone 1 records it but does not yet extract it —
  see "deliberately deferred" above).

## License

[MIT](LICENSE)
