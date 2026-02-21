from types import SimpleNamespace

import pytest

from app.services import cloud_tasks
from app.utils.errors import AppError


def test_enqueue_job_task_uses_cloud_tasks_in_cloud_mode(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        cloud_tasks,
        "get_settings",
        lambda: SimpleNamespace(jobs_force_inline=False, is_cloud_mode=True),
    )
    monkeypatch.setattr(
        cloud_tasks,
        "_enqueue_cloud_task_payload",
        lambda *, payload, delay_seconds=0: captured.update({"payload": payload, "delay_seconds": delay_seconds}),
    )
    monkeypatch.setattr(
        cloud_tasks,
        "_enqueue_rq_payload",
        lambda *, payload: pytest.fail("RQ path should not be used in cloud mode"),
    )

    cloud_tasks.enqueue_job_task(job_id="job_cloud")

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["kind"] == "job"
    assert payload["job_id"] == "job_cloud"


def test_enqueue_step_task_uses_rq_in_local_mode(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        cloud_tasks,
        "get_settings",
        lambda: SimpleNamespace(jobs_force_inline=False, is_cloud_mode=False),
    )
    monkeypatch.setattr(
        cloud_tasks,
        "_enqueue_rq_payload",
        lambda *, payload: captured.update({"payload": payload}),
    )
    monkeypatch.setattr(
        cloud_tasks,
        "_enqueue_cloud_task_payload",
        lambda *, payload, delay_seconds=0: pytest.fail("Cloud Tasks path should not be used in local mode"),
    )

    cloud_tasks.enqueue_step_task(job_id="job_local", step="GEOCODE")

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["kind"] == "pipeline_step"
    assert payload["job_id"] == "job_local"
    assert payload["step"] == "GEOCODE"


def test_enqueue_job_task_cloud_mode_failure_does_not_fallback_to_rq(monkeypatch):
    monkeypatch.setattr(
        cloud_tasks,
        "get_settings",
        lambda: SimpleNamespace(jobs_force_inline=False, is_cloud_mode=True),
    )
    monkeypatch.setattr(
        cloud_tasks,
        "_enqueue_cloud_task_payload",
        lambda *, payload, delay_seconds=0: (_ for _ in ()).throw(
            AppError(message="boom", error_code="CLOUD_TASKS_ENQUEUE_FAILED", status_code=503, stage="TASKS")
        ),
    )
    monkeypatch.setattr(
        cloud_tasks,
        "_enqueue_rq_payload",
        lambda *, payload: pytest.fail("RQ fallback must not run in cloud mode"),
    )

    with pytest.raises(AppError) as exc:
        cloud_tasks.enqueue_job_task(job_id="job_fail")

    assert exc.value.error_code == "CLOUD_TASKS_ENQUEUE_FAILED"


def test_dispatch_enqueued_task_routes_job_and_pipeline(monkeypatch):
    import app.services.job_pipeline as job_pipeline
    import app.services.jobs as jobs_service

    called: dict[str, object] = {}
    monkeypatch.setattr(jobs_service, "run_queued_job", lambda job_id: called.update({"job_id": job_id}))
    monkeypatch.setattr(job_pipeline, "process_task_payload", lambda payload: called.update({"pipeline": payload}))

    cloud_tasks.dispatch_enqueued_task({"kind": "job", "job_id": "job_route"})
    assert called.get("job_id") == "job_route"

    cloud_tasks.dispatch_enqueued_task({"job_id": "job_pipeline", "step": "OPTIMIZE"})
    pipeline_payload = called.get("pipeline")
    assert isinstance(pipeline_payload, dict)
    assert pipeline_payload["step"] == "OPTIMIZE"
