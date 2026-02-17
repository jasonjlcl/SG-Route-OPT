from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.schemas.api import JobAcceptedResponse, OptimizeJobRequest
from app.services.job_pipeline import create_optimize_pipeline_job
from app.services.jobs import get_job_or_404, get_steps_state, parse_result_ref
from app.utils.errors import AppError
from app.utils.db import SessionLocal, get_db

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _job_payload(job) -> dict:
    return {
        "job_id": job.id,
        "type": job.type,
        "status": job.status,
        "progress": job.progress,
        "progress_pct": job.progress_pct,
        "current_step": job.current_step,
        "message": job.message,
        "error_code": job.error_code,
        "error_detail": job.error_detail,
        "steps": get_steps_state(job),
        "result_ref": parse_result_ref(job),
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


@router.post("/optimize")
def start_optimize_job(payload: OptimizeJobRequest, db: Session = Depends(get_db)) -> dict:
    job = create_optimize_pipeline_job(
        db,
        dataset_id=payload.dataset_id,
        depot_lat=payload.depot_lat,
        depot_lon=payload.depot_lon,
        num_vehicles=payload.fleet_config.num_vehicles,
        capacity=payload.fleet_config.capacity,
        workday_start=payload.workday_start,
        workday_end=payload.workday_end,
        solver_time_limit_s=payload.solver.solver_time_limit_s,
        allow_drop_visits=payload.solver.allow_drop_visits,
        use_live_traffic=payload.use_live_traffic,
    )
    return JobAcceptedResponse(job_id=job.id, type=job.type).model_dump()


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
                if job.status in {"SUCCEEDED", "FAILED", "CANCELED", "CANCELLED"}:
                    break
            finally:
                db.close()
            await asyncio.sleep(1.0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{job_id}/file")
def get_job_file(job_id: str, db: Session = Depends(get_db)):
    job = get_job_or_404(db, job_id)
    result = parse_result_ref(job) or {}
    file_path = result.get("file_path")
    if not file_path:
        driver_pack = result.get("driver_pack") if isinstance(result.get("driver_pack"), dict) else {}
        signed_url = result.get("signed_url") or driver_pack.get("signed_url")
        if signed_url:
            return RedirectResponse(str(signed_url))
    if not file_path:
        raise AppError(message="Job has no file result", error_code="NOT_FOUND", status_code=404)
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise AppError(message="Generated file not found", error_code="NOT_FOUND", status_code=404)
    return FileResponse(path)
