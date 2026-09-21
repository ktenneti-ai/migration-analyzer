from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.metadata import store

router = APIRouter(prefix="/api/projects", tags=["powerbi"])


def _get_data(session: Session, project_id: str):
    data = store.get_project_data(session, project_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return data


@router.get("/{project_id}/powerbi/tables")
def tables(project_id: str, session: Session = Depends(db_session)):
    data = _get_data(session, project_id)
    out = []
    for model in data.semantic_models:
        for table in model.tables:
            out.append(
                {
                    "object_type": "TABLE",
                    "name": table.name,
                    "parent": model.name,
                    "source": table.source_hint,
                    "columns": len(table.columns),
                    "measures": len(table.measures),
                    "status": table.status,
                }
            )
    return out


@router.get("/{project_id}/powerbi/measures")
def measures(project_id: str, session: Session = Depends(db_session)):
    data = _get_data(session, project_id)
    out = []
    for model in data.semantic_models:
        for table in model.tables:
            for measure in table.measures:
                out.append(
                    {
                        "name": measure.name,
                        "table": table.name,
                        "expression": measure.expression,
                        "referenced_measures": measure.referenced_measures,
                        "referenced_columns": measure.referenced_columns,
                        "dependent_tables": measure.dependent_tables,
                        "dependency_depth": measure.dependency_depth,
                        "status": measure.status,
                        "functions_used": measure.functions_used,
                        "complexity_score": measure.complexity_score,
                        "complexity_band": measure.complexity_band,
                        "complexity_category": measure.complexity_category,
                        "complexity_reasons": measure.complexity_reasons,
                    }
                )
    return out


@router.get("/{project_id}/powerbi/relationships")
def relationships(project_id: str, session: Session = Depends(db_session)):
    data = _get_data(session, project_id)
    out = []
    for model in data.semantic_models:
        for rel in model.relationships:
            out.append(
                {
                    "from_table": rel.from_table,
                    "from_column": rel.from_column,
                    "to_table": rel.to_table,
                    "to_column": rel.to_column,
                    "cardinality": rel.cardinality,
                    "cross_filter_direction": rel.cross_filter_direction,
                    "is_active": rel.is_active,
                    "status": rel.status,
                }
            )
    return out


@router.get("/{project_id}/gaps")
def gaps(project_id: str, session: Session = Depends(db_session)):
    data = _get_data(session, project_id)
    return [g.model_dump() for g in data.gaps]
