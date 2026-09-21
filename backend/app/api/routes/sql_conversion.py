"""Spec section 20 / Output section 7 (SQL Conversion Report).

Note: the spec envisions Teradata SQL -> Databricks SQL conversion, which
still requires Teradata ingestion (not implemented). What's implemented
instead — and what pbi-unified's own scope actually is — is the adjacent,
buildable-today capability: Power BI DAX measure -> Databricks SQL
translation (backend/app/parsers/dax/sql_translator.py), gated by the
DAX complexity classifier. The response shape stays stable so a future
Teradata-SQL conversion item can be added alongside these without a
frontend change.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.metadata import store
from app.parsers.dax.sql_translator import translate_model

router = APIRouter(prefix="/api/projects", tags=["sql-conversion"])


@router.get("/{project_id}/sql-conversion")
def sql_conversion(project_id: str, session: Session = Depends(db_session)):
    data = store.get_project_data(session, project_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")

    items = []
    for model in data.semantic_models:
        items.extend(translate_model(model))

    return {
        "pending": len(items) == 0,
        "reason": (
            "No Power BI semantic model has been ingested yet, so there are no DAX measures "
            "to translate. (Teradata SQL -> Databricks SQL conversion additionally requires "
            "Teradata ingestion, which is not implemented yet.)"
            if not items
            else "These are Power BI DAX measures translated to Databricks SQL (status auto/"
            "auto_spot_check), gated by the DAX complexity classifier. Teradata SQL -> Databricks "
            "SQL conversion still requires Teradata ingestion, which is not implemented yet."
        ),
        "items": [i.model_dump() for i in items],
    }
