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
        # utf-8-sig strips a leading byte-order-mark if present (common from
        # PowerShell/Tabular Editor JSON exports on Windows) and otherwise
        # behaves exactly like utf-8 — without this, a BOM'd file fails with
        # a confusing "Expecting value: line 1 column 1 (char 0)" JSON error.
        raw_text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"'{file.filename}' is not a UTF-8 text file (found invalid bytes at position {exc.start}). "
            "Confirm it was exported as UTF-8 JSON, not a binary format like .pbix renamed to .json.",
        ) from exc
    try:
        result = ingest_json_file(session, project_id, file.filename, raw_text)
    except IngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result
