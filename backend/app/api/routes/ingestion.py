from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.ingestion.service import IngestionError, ingest_json_file

router = APIRouter(prefix="/api/projects", tags=["ingestion"])


@router.post("/{project_id}/ingest")
async def ingest(project_id: str, file: UploadFile, session: Session = Depends(db_session)):
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(
            status_code=400,
            detail="Milestone 1 supports .json files only; other formats are a future milestone.",
        )
    raw_bytes = await file.read()
    try:
        result = ingest_json_file(session, project_id, file.filename, raw_bytes.decode("utf-8"))
    except IngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result
