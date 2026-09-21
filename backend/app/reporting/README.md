# Reporting / exports

`blueprint.py` builds the Migration Assessment Report from whatever the
canonical model currently holds — sections backed by real data (Power BI
inventory, DAX analysis, migration gaps, cross-model overlap) are computed;
sections that need ingestion/engines that don't exist yet (Teradata,
Databricks, SQL conversion, validation, complexity classification) are
rendered as `REQUIRES_INPUT` placeholders naming what's missing, per spec
section 13.

`exporters.py` renders that report to PDF (reportlab) and DOCX
(python-docx) for download via `GET /api/projects/{id}/report/export`.

CSV/Excel export of the tabular inventories (spec section 15) is not yet
implemented.
