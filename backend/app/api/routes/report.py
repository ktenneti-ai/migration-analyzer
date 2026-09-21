from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.metadata import store
from app.reporting import exporters
from app.reporting.blueprint import build_report

router = APIRouter(prefix="/api/projects", tags=["report"])


def _load_report(project_id: str, session: Session):
    data = store.get_project_data(session, project_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")
    snapshot = store.get_graph_snapshot(session, project_id)
    graph_summary = json.loads(snapshot) if snapshot and snapshot != "{}" else {"nodes": [], "edges": []}
    return build_report(data, graph_summary)


@router.get("/{project_id}/report")
def get_report(project_id: str, session: Session = Depends(db_session)):
    return _load_report(project_id, session).model_dump()


@router.get("/{project_id}/report/export")
def export_report(
    project_id: str,
    format: str = Query(..., pattern="^(pdf|docx)$"),
    session: Session = Depends(db_session),
):
    report = _load_report(project_id, session)
    filename = f"{report.project_name.replace(' ', '_')}_assessment_report.{format}"

    if format == "pdf":
        content = exporters.render_pdf(report)
        media_type = "application/pdf"
    else:
        content = exporters.render_docx(report)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
