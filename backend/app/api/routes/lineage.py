from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.metadata import store

router = APIRouter(prefix="/api/projects", tags=["lineage"])


@router.get("/{project_id}/lineage")
def lineage(project_id: str, session: Session = Depends(db_session)):
    snapshot = store.get_graph_snapshot(session, project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not snapshot or snapshot == "{}":
        return {"nodes": [], "edges": []}
    return json.loads(snapshot)
