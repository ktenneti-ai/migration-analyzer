from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.metadata import store
from app.migration.plan import build_phase_plan

router = APIRouter(prefix="/api/projects", tags=["migration-plan"])


@router.get("/{project_id}/migration-plan")
def migration_plan(project_id: str, session: Session = Depends(db_session)):
    data = store.get_project_data(session, project_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return [phase.model_dump() for phase in build_phase_plan(data)]
