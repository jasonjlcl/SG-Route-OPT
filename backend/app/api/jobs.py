from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.services.jobs import get_job_or_404, parse_result_ref
from app.utils.errors import AppError
from app.utils.db import SessionLocal, get_db

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _job_payload(job) -> dict:
    return {
        "job_id": job.id,
        "type": job.type,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "result_ref": parse_result_ref(job),
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = get_job_or_404(db, job_id)
    return _job_payload(job)


@router.get("/{job_id}/events")
async def get_job_events(job_id: str) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        last_updated = None
        while True:
            db = SessionLocal()
            try:
                job = get_job_or_404(db, job_id)
                stamp = job.updated_at.isoformat()
                if stamp != last_updated:
                    last_updated = stamp
                    payload = _job_payload(job)
                    yield f"data: {json.dumps(payload)}\n\n"
                if job.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                    break
            finally:
                db.close()
            await asyncio.sleep(1.0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{job_id}/file")
def get_job_file(job_id: str, db: Session = Depends(get_db)) -> FileResponse:
    job = get_job_or_404(db, job_id)
    result = parse_result_ref(job) or {}
    file_path = result.get("file_path")
    if not file_path:
        raise AppError(message="Job has no file result", error_code="NOT_FOUND", status_code=404)
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise AppError(message="Generated file not found", error_code="NOT_FOUND", status_code=404)
    return FileResponse(path)
