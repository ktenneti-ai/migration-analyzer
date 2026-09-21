from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.metadata import store
from app.metadata.aggregates import compute_dashboard

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str


@router.post("")
def create_project(body: CreateProjectRequest, session: Session = Depends(db_session)):
    data = store.create_project(session, body.name)
    return data.project.model_dump()


@router.get("")
def list_projects(session: Session = Depends(db_session)):
    return [p.model_dump() for p in store.list_projects(session)]


@router.get("/{project_id}")
def get_project(project_id: str, session: Session = Depends(db_session)):
    data = store.get_project_data(session, project_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return data.project.model_dump()


@router.get("/{project_id}/dashboard")
def dashboard(project_id: str, session: Session = Depends(db_session)):
    data = store.get_project_data(session, project_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return compute_dashboard(data)
