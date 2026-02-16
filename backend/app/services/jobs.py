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


def _parse_json_blob(value: str | None, *, default: Any) -> Any:
    if not value:
        return default
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return default
    return parsed


def _empty_steps_state() -> dict[str, dict[str, Any]]:
    return {}


def create_job(db: Session, *, job_type: str, payload: dict[str, Any]) -> Job:
    job = Job(
        id=f"job_{uuid.uuid4().hex}",
        type=job_type,
        status="QUEUED",
        progress=0,
        progress_pct=0,
        message="Queued",
        payload_json=_json(payload),
        steps_json=_json(_empty_steps_state()),
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
    progress_pct: int | None = None,
    current_step: str | None = None,
    message: str | None = None,
    error_code: str | None = None,
    error_detail: str | dict[str, Any] | None = None,
    result_ref: dict[str, Any] | None = None,
) -> Job:
    job = get_job_or_404(db, job_id)
    job.status = status
    if progress is not None:
        job.progress = max(0, min(100, int(progress)))
        job.progress_pct = job.progress
    if progress_pct is not None:
        job.progress_pct = max(0, min(100, int(progress_pct)))
        job.progress = job.progress_pct
    if current_step is not None:
        job.current_step = current_step
    if message is not None:
        job.message = message[:512]
    if error_code is not None:
        job.error_code = error_code[:128]
    if error_detail is not None:
        if isinstance(error_detail, dict):
            job.error_detail = _json(error_detail)
        else:
            job.error_detail = str(error_detail)[:2000]
    if result_ref is not None:
        job.result_ref = _json(result_ref)
    if status in {"SUCCEEDED"}:
        job.error_code = None
        job.error_detail = None
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


def parse_payload(job: Job) -> dict[str, Any]:
    value = _parse_json_blob(job.payload_json, default={})
    return value if isinstance(value, dict) else {}


def get_steps_state(job: Job) -> dict[str, dict[str, Any]]:
    value = _parse_json_blob(job.steps_json, default={})
    if isinstance(value, dict):
        return value
    return {}


def save_steps_state(db: Session, *, job_id: str, steps_state: dict[str, dict[str, Any]]) -> Job:
    job = get_job_or_404(db, job_id)
    job.steps_json = _json(steps_state)
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job


def ensure_step_entry(steps_state: dict[str, dict[str, Any]], step: str) -> dict[str, Any]:
    entry = steps_state.get(step)
    if not isinstance(entry, dict):
        entry = {"status": "PENDING"}
        steps_state[step] = entry
    return entry


def lock_step(db: Session, *, job_id: str, step: str, lock_token: str) -> bool:
    job = get_job_or_404(db, job_id)
    if job.status in {"FAILED", "SUCCEEDED", "CANCELED", "CANCELLED"}:
        return False

    steps = get_steps_state(job)
    entry = ensure_step_entry(steps, step)
    status = str(entry.get("status") or "PENDING")
    if status in {"RUNNING", "SUCCEEDED"}:
        return False

    entry["status"] = "RUNNING"
    entry["lock_token"] = lock_token
    entry["updated_at"] = datetime.utcnow().isoformat()
    job.steps_json = _json(steps)
    job.current_step = step
    job.updated_at = datetime.utcnow()
    db.commit()
    return True


def complete_step(
    db: Session,
    *,
    job_id: str,
    step: str,
    lock_token: str,
    progress_pct: int,
    message: str,
) -> Job:
    job = get_job_or_404(db, job_id)
    steps = get_steps_state(job)
    entry = ensure_step_entry(steps, step)
    if entry.get("lock_token") != lock_token and entry.get("status") == "RUNNING":
        # Another worker lock won this step.
        return job

    entry["status"] = "SUCCEEDED"
    entry["lock_token"] = None
    entry["updated_at"] = datetime.utcnow().isoformat()
    job.steps_json = _json(steps)
    return set_job_status(
        db,
        job_id=job_id,
        status="RUNNING",
        progress_pct=progress_pct,
        current_step=step,
        message=message,
    )


def fail_step(
    db: Session,
    *,
    job_id: str,
    step: str,
    lock_token: str,
    error_code: str,
    error_detail: str | dict[str, Any],
) -> Job:
    job = get_job_or_404(db, job_id)
    steps = get_steps_state(job)
    entry = ensure_step_entry(steps, step)
    if entry.get("lock_token") and entry.get("lock_token") != lock_token and entry.get("status") == "RUNNING":
        return job

    entry["status"] = "FAILED"
    entry["lock_token"] = None
    entry["updated_at"] = datetime.utcnow().isoformat()
    entry["error_code"] = error_code
    entry["error_detail"] = error_detail if isinstance(error_detail, str) else _json(error_detail)
    job.steps_json = _json(steps)
    return set_job_status(
        db,
        job_id=job_id,
        status="FAILED",
        progress_pct=max(job.progress_pct, job.progress, 1),
        current_step=step,
        message=str(error_code),
        error_code=error_code,
        error_detail=error_detail,
    )


def _run_job_inline(job_id: str) -> None:
    from app.services.job_tasks import run_job

    db = SessionLocal()
    try:
        job = get_job_or_404(db, job_id)
        payload = parse_payload(job)
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
