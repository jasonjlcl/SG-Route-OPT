from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from typing import Any

from redis import Redis
from rq import Queue, Worker
from sqlalchemy.orm import Session

from app.models import Job
from app.utils.db import SessionLocal
from app.utils.errors import AppError
from app.utils.settings import get_settings


def _json(data: Any) -> str:
    return json.dumps(data, default=str)


def create_job(db: Session, *, job_type: str, payload: dict[str, Any]) -> Job:
    job = Job(
        id=f"job_{uuid.uuid4().hex}",
        type=job_type,
        status="QUEUED",
        progress=0,
        message="Queued",
        payload_json=_json(payload),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job_or_404(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise AppError(message=f"Job {job_id} not found", error_code="NOT_FOUND", status_code=404)
    return job


def set_job_status(
    db: Session,
    *,
    job_id: str,
    status: str,
    progress: int | None = None,
    message: str | None = None,
    result_ref: dict[str, Any] | None = None,
) -> Job:
    job = get_job_or_404(db, job_id)
    job.status = status
    if progress is not None:
        job.progress = max(0, min(100, int(progress)))
    if message is not None:
        job.message = message[:512]
    if result_ref is not None:
        job.result_ref = _json(result_ref)
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job


def parse_result_ref(job: Job) -> dict[str, Any] | None:
    if not job.result_ref:
        return None
    try:
        value = json.loads(job.result_ref)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    return {"raw": job.result_ref}


def _run_job_inline(job_id: str) -> None:
    from app.services.job_tasks import run_job

    db = SessionLocal()
    try:
        job = get_job_or_404(db, job_id)
        payload = json.loads(job.payload_json) if job.payload_json else {}
        run_job(job_id=job.id, job_type=job.type, payload=payload)
    finally:
        db.close()


def enqueue_job(job: Job) -> None:
    settings = get_settings()
    if settings.jobs_force_inline:
        _run_job_inline(job.id)
        return

    def _enqueue_inline_thread() -> None:
        thread = threading.Thread(target=_run_job_inline, args=(job.id,), daemon=True)
        thread.start()

    try:
        redis_conn = Redis.from_url(settings.redis_url)
        redis_conn.ping()
        queue = Queue("default", connection=redis_conn)
        worker_count = Worker.count(connection=redis_conn, queue=queue)
        if worker_count <= 0:
            _enqueue_inline_thread()
            return
        queue.enqueue("app.services.job_tasks.run_job", job_id=job.id, job_type=job.type, payload=json.loads(job.payload_json))
        return
    except Exception:
        _enqueue_inline_thread()
