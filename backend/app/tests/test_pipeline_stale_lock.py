import json
from datetime import datetime, timedelta

import pytest

from app.services.job_pipeline import process_task_payload
from app.services.jobs import create_job, get_job_or_404, lock_step
from app.utils.db import SessionLocal


def _steps_with(overrides: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    steps = {
        "GEOCODE": {"status": "PENDING"},
        "BUILD_MATRIX": {"status": "PENDING"},
        "OPTIMIZE": {"status": "PENDING"},
        "GENERATE_EXPORTS": {"status": "PENDING"},
    }
    for step, fields in overrides.items():
        steps.setdefault(step, {}).update(fields)
    return steps


def _create_optimize_job(*, status: str, steps: dict[str, dict[str, object]]) -> str:
    db = SessionLocal()
    try:
        job = create_job(db, job_type="OPTIMIZE", payload={"dataset_id": 1})
        job.status = status
        job.steps_json = json.dumps(steps)
        db.commit()
        db.refresh(job)
        return job.id
    finally:
        db.close()


def test_lock_step_reclaims_stale_running_step():
    stale_at = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
    job_id = _create_optimize_job(
        status="RUNNING",
        steps=_steps_with(
            {
                "GEOCODE": {
                    "status": "RUNNING",
                    "lock_token": "old-token",
                    "updated_at": stale_at,
                }
            }
        ),
    )

    db = SessionLocal()
    try:
        claimed = lock_step(db, job_id=job_id, step="GEOCODE", lock_token="new-token", lease_seconds=60)
        assert claimed is True

        job = get_job_or_404(db, job_id)
        steps = json.loads(job.steps_json or "{}")
        geocode = steps["GEOCODE"]
        assert geocode["status"] == "RUNNING"
        assert geocode["lock_token"] == "new-token"
        assert geocode["stale_reclaimed"] == 1
        assert geocode.get("lease_expires_at")
    finally:
        db.close()


def test_lock_step_keeps_fresh_running_lock():
    fresh_until = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    job_id = _create_optimize_job(
        status="RUNNING",
        steps=_steps_with(
            {
                "GEOCODE": {
                    "status": "RUNNING",
                    "lock_token": "active-token",
                    "updated_at": datetime.utcnow().isoformat(),
                    "lease_expires_at": fresh_until,
                }
            }
        ),
    )

    db = SessionLocal()
    try:
        claimed = lock_step(db, job_id=job_id, step="GEOCODE", lock_token="other-token", lease_seconds=60)
        assert claimed is False

        job = get_job_or_404(db, job_id)
        steps = json.loads(job.steps_json or "{}")
        geocode = steps["GEOCODE"]
        assert geocode["status"] == "RUNNING"
        assert geocode["lock_token"] == "active-token"
    finally:
        db.close()


def test_process_task_payload_final_step_redelivery_marks_job_succeeded():
    job_id = _create_optimize_job(
        status="RUNNING",
        steps=_steps_with(
            {
                "GEOCODE": {"status": "SUCCEEDED"},
                "BUILD_MATRIX": {"status": "SUCCEEDED"},
                "OPTIMIZE": {"status": "SUCCEEDED"},
                "GENERATE_EXPORTS": {"status": "SUCCEEDED"},
            }
        ),
    )

    process_task_payload({"job_id": job_id, "step": "GENERATE_EXPORTS"})

    db = SessionLocal()
    try:
        job = get_job_or_404(db, job_id)
        assert job.status == "SUCCEEDED"
        assert int(job.progress_pct or 0) == 100
        assert job.message == "All optimization steps completed"
    finally:
        db.close()


def test_process_task_payload_step_redelivery_requeues_next_step(monkeypatch):
    captured: dict[str, str] = {}
    job_id = _create_optimize_job(
        status="RUNNING",
        steps=_steps_with(
            {
                "GEOCODE": {"status": "SUCCEEDED"},
                "BUILD_MATRIX": {"status": "PENDING"},
            }
        ),
    )

    monkeypatch.setattr(
        "app.services.job_pipeline.enqueue_step_task",
        lambda *, job_id, step, delay_seconds=0: captured.update({"job_id": job_id, "step": step}),
    )

    process_task_payload({"job_id": job_id, "step": "GEOCODE"})

    assert captured == {"job_id": job_id, "step": "BUILD_MATRIX"}


def test_process_task_payload_skips_merge_when_lock_is_lost(monkeypatch):
    job_id = _create_optimize_job(
        status="RUNNING",
        steps=_steps_with(
            {
                "GEOCODE": {"status": "PENDING"},
            }
        ),
    )

    monkeypatch.setattr("app.services.job_pipeline._run_geocode_step", lambda **kwargs: {"geocode": {"ok": True}})
    monkeypatch.setattr("app.services.job_pipeline.has_step_lock", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        "app.services.job_pipeline._merge_result",
        lambda *args, **kwargs: pytest.fail("merge should not run after lock ownership is lost"),
    )
    monkeypatch.setattr(
        "app.services.job_pipeline.complete_step",
        lambda *args, **kwargs: pytest.fail("step completion should not run after lock ownership is lost"),
    )

    process_task_payload({"job_id": job_id, "step": "GEOCODE"})
