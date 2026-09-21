# Architecture

## Pipeline

Every input format is meant to converge on one pipeline and one canonical
model, rather than a separate migration engine per format:

```
PBIX / PBIP / PBIT / JSON / TMDL / SQL / CSV / Excel
                    |
              Input Adapters        (backend/app/ingestion/)
                    |
                Extraction          (backend/app/extractors/)
                    |
              Normalization         (adapters + extractors write into the canonical model)
                    |
        Canonical Metadata Model    (backend/app/metadata/models.py)
                    |
       Lineage / Dependency Graph   (backend/app/graph/)
                    |
                 Analysis           (backend/app/parsers/, backend/app/recommendations/ — future)
                    |
          Migration Intelligence    (backend/app/migration/ — future)
                    |
                  Output            (backend/app/api/, backend/app/reporting/ — future, frontend/)
```

Milestone 1 implements the JSON branch end-to-end (detection → Power BI
extraction → DAX dependency resolution → canonical model → lineage graph →
API → UI) and leaves the other branches as adapters/extractors to be added
later without reshaping the pipeline or the canonical model.

## Canonical metadata model

`backend/app/metadata/models.py` is the single source of truth for object
shape, used by every adapter regardless of input format. Every object that
is extracted or inferred carries:

- `status`: `CONFIRMED` (directly read from source metadata), `INFERRED`
  (derived from analysis, with evidence), or `REQUIRES_INPUT` (cannot be
  determined from what was supplied — never fabricated).
- `provenance` (where applicable): `source_file`, `source_type`,
  `json_path`, `extracted_at`.

Milestone 1 populates the Power BI side of the model
(`PowerBISemanticModel`, `PowerBITable`, `PowerBIColumn`, `PowerBIMeasure`,
`PowerBIRelationship`) plus a generic `MigrationGap` for unresolved
references. `TeradataTable` and `DatabricksTable` exist as skeletons so a
later milestone's adapters slot into the same model rather than requiring a
reshape.

`ProjectData` is the persisted unit: one project's canonical objects plus
its gaps. It's stored as a JSON blob per project in SQLite
(`backend/app/db/`) — chosen over mapping every nested object into its own
table, since the model's shape will keep growing across milestones and the
Pydantic models are already the schema of record.

## Graph model

`backend/app/graph/builder.py` derives a lineage graph from the canonical
model: `LineageNode`/`LineageEdge` (also defined once, in
`metadata/models.py`) for semantic models, tables, columns, and measures,
connected by containment edges (column→table, measure→table),
relationship edges (table→table), and dependency edges
(measure→measure, measure→column) computed by the DAX dependency parser.
The graph is exposed as JSON (`GET /api/projects/{id}/lineage`) for the
frontend's React Flow-based Lineage Explorer, and is rebuilt and
snapshotted to storage on every ingestion.

## DAX dependency parsing (Milestone 1 scope)

`backend/app/parsers/dax/dependency_parser.py` extracts `[Bare Name]` and
`Table[Column]` / `'Table Name'[Column]` references from a measure's DAX
expression via regex, not a full DAX grammar. A bare reference resolves to
a measure if the name matches a known measure, otherwise to a column in
the measure's own table; anything that resolves to neither becomes a
`MigrationGap`. Dependency depth is computed by traversing the resulting
measure→measure edges with a cycle guard. A real DAX AST (recognizing
`CALCULATE`, `FILTER`, time-intelligence functions, etc., per the full
spec) is a later milestone — this module's job is only to get the
dependency graph and gap detection right for typical measure expressions.

## API surface (Milestone 1)

See `backend/app/api/routes/`: `projects.py` (create/list/get project +
dashboard counts), `ingestion.py` (JSON upload), `powerbi.py`
(tables/measures/relationships/gaps inventories), `lineage.py` (graph
snapshot). All dashboard counts are computed from the canonical model on
every request — never hardcoded — so the shape is stable even as later
milestones add Teradata/Databricks/complexity data to fill in the zeros
Milestone 1 currently returns for those fields.

## Frontend

React + TypeScript (Vite), React Router for the nav shell, React Flow for
the Lineage Explorer. `frontend/src/types/canonical.ts` mirrors the
backend's canonical model so every page renders through the same shapes
regardless of which pipeline stage produced the data. The nav
(`frontend/src/components/layout/Nav.tsx`) lists the full target
information architecture from day one; sections beyond Milestone 1's scope
are shown but inert, so the app's eventual shape is visible early.

## Testing

- Backend: pytest, with unit tests per pipeline stage (detector, adapter,
  dependency parser, graph builder) plus API integration tests
  (`backend/tests/test_api.py`) that exercise the full upload → inventory →
  lineage round trip against a temporary SQLite database.
- Frontend: Vitest + React Testing Library component tests
  (`InventoryTable`, `LineageGraph`).
- `sample_data/finance_model.json` is the shared fixture across both test
  suites and the manual walkthrough in the README, so a change to the
  canonical model's shape surfaces failures in one place.
