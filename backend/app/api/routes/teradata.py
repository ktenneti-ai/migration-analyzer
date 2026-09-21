"""Teradata objects referenced from the ingested Power BI model.

Milestone 1 has no Teradata SQL/DDL ingestion pipeline, so "views" and
"base tables" (data.teradata_views / data.teradata_base_tables in
compute_dashboard) legitimately stay at zero until that exists. But every
TMDL table's partition M query names its exact upstream Teradata object
(see tmdl_adapter.py's `_extract_teradata_source_hint`), so there IS real
Teradata-side information already sitting in the canonical model — this
router surfaces it rather than leaving the Teradata Assessment page with
nothing to show but zeros.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.ingestion.tmdl.tmdl_adapter import TERADATA_SOURCE_HINT_PREFIX, parse_teradata_source_hint
from app.metadata import store

router = APIRouter(prefix="/api/projects", tags=["teradata"])


def _get_data(session: Session, project_id: str):
    data = store.get_project_data(session, project_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return data


@router.get("/{project_id}/teradata/referenced-objects")
def referenced_objects(project_id: str, session: Session = Depends(db_session)):
    data = _get_data(session, project_id)
    out = []
    for model in data.semantic_models:
        for table in model.tables:
            if table.display_name is not None:
                continue  # Power BI auto-date system table, not a real Teradata object
            if not table.source_hint or not table.source_hint.startswith(TERADATA_SOURCE_HINT_PREFIX):
                continue
            parsed = parse_teradata_source_hint(table.source_hint)
            out.append(
                {
                    "model": model.name,
                    "power_bi_table": table.name,
                    "teradata_database": parsed["database"],
                    "teradata_schema": parsed["schema"],
                    "teradata_object": parsed["object"],
                    "teradata_object_type": parsed["object_type"],
                    "columns": len(table.columns),
                    "measures": len(table.measures),
                    "source_file": table.provenance.source_file,
                    "status": table.status,
                }
            )
    return out


@router.get("/{project_id}/teradata/unresolved-tables")
def unresolved_tables(project_id: str, session: Session = Depends(db_session)):
    data = _get_data(session, project_id)
    out = []
    for model in data.semantic_models:
        for table in model.tables:
            if table.display_name is not None:
                continue
            if table.source_hint:
                continue
            out.append(
                {
                    "model": model.name,
                    "power_bi_table": table.name,
                    "columns": len(table.columns),
                    "measures": len(table.measures),
                    "source_file": table.provenance.source_file,
                    "reason": (
                        "No Teradata source recognized in this table's partition "
                        "(not a Teradata.Database(...) M query, or the table has no "
                        "partition at all)."
                    ),
                }
            )
    return out
