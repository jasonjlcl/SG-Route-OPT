from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from redis import Redis
from rq import Queue

from app.utils.errors import AppError
from app.utils.settings import get_settings

try:
    from google.cloud import tasks_v2
    from google.protobuf import timestamp_pb2

    CLOUD_TASKS_AVAILABLE = True
except Exception:  # noqa: BLE001
    CLOUD_TASKS_AVAILABLE = False

logger = logging.getLogger(__name__)


def cloud_tasks_enabled() -> bool:
    settings = get_settings()
    return bool(
        CLOUD_TASKS_AVAILABLE
        and settings.gcp_project_id
        and settings.gcp_region
        and settings.cloud_tasks_queue
        and settings.app_base_url
    )


def dispatch_enqueued_task(payload: dict[str, Any]) -> None:
    kind = str(payload.get("kind") or "pipeline_step").strip().lower()
    if kind == "job":
        from app.services.jobs import run_queued_job

        run_queued_job(str(payload.get("job_id") or ""))
        return

    from app.services.job_pipeline import process_task_payload

    process_task_payload(payload)


def _enqueue_rq_payload(*, payload: dict[str, Any]) -> None:
    settings = get_settings()
    redis_conn = Redis.from_url(settings.redis_url)
    redis_conn.ping()
    queue = Queue("default", connection=redis_conn)
    queue.enqueue("app.services.cloud_tasks.dispatch_enqueued_task", payload=payload)


def _enqueue_cloud_task_payload(*, payload: dict[str, Any], delay_seconds: int = 0) -> None:
    settings = get_settings()
    if not cloud_tasks_enabled():
        raise AppError(
            message="Cloud Tasks is not configured for cloud mode",
            error_code="CLOUD_TASKS_NOT_CONFIGURED",
            status_code=500,
            stage="TASKS",
        )

    client = tasks_v2.CloudTasksClient()
    queue_path = client.queue_path(settings.gcp_project_id, settings.gcp_region, settings.cloud_tasks_queue)
    handler_url = f"{settings.app_base_url.rstrip('/')}/tasks/handle"

    http_request: dict[str, Any] = {
        "http_method": tasks_v2.HttpMethod.POST,
        "url": handler_url,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload).encode("utf-8"),
    }
    if settings.cloud_tasks_service_account:
        http_request["oidc_token"] = {
            "service_account_email": settings.cloud_tasks_service_account,
            "audience": settings.cloud_tasks_audience or handler_url,
        }

    task: dict[str, Any] = {"http_request": http_request}
    if delay_seconds > 0:
        ts = timestamp_pb2.Timestamp()
        ts.FromDatetime(datetime.now(timezone.utc) + timedelta(seconds=delay_seconds))
        task["schedule_time"] = ts

    try:
        client.create_task(parent=queue_path, task=task)
    except Exception as exc:  # noqa: BLE001
        raise AppError(
            message="Failed to enqueue Cloud Task",
            error_code="CLOUD_TASKS_ENQUEUE_FAILED",
            status_code=503,
            stage="TASKS",
            details={"cause": str(exc)},
        ) from exc


def enqueue_step_task(*, job_id: str, step: str, delay_seconds: int = 0) -> None:
    payload = {"kind": "pipeline_step", "job_id": job_id, "step": step}
    settings = get_settings()

    if settings.jobs_force_inline:
        dispatch_enqueued_task(payload)
        return

    if settings.is_cloud_mode:
        _enqueue_cloud_task_payload(payload=payload, delay_seconds=delay_seconds)
        return

    if delay_seconds > 0:
        logger.warning("delay_seconds is ignored for local RQ dispatch: job=%s step=%s", job_id, step)
    try:
        _enqueue_rq_payload(payload=payload)
    except Exception as exc:  # noqa: BLE001
        raise AppError(
            message="Failed to enqueue local step task to RQ",
            error_code="RQ_ENQUEUE_FAILED",
            status_code=503,
            stage="TASKS",
            details={"cause": str(exc), "job_id": job_id, "step": step},
        ) from exc


def enqueue_job_task(*, job_id: str, delay_seconds: int = 0) -> None:
    payload = {"kind": "job", "job_id": job_id}
    settings = get_settings()

    if settings.jobs_force_inline:
        dispatch_enqueued_task(payload)
        return

    if settings.is_cloud_mode:
        _enqueue_cloud_task_payload(payload=payload, delay_seconds=delay_seconds)
        return

    if delay_seconds > 0:
        logger.warning("delay_seconds is ignored for local RQ dispatch: job=%s", job_id)
    try:
        _enqueue_rq_payload(payload=payload)
    except Exception as exc:  # noqa: BLE001
        raise AppError(
            message="Failed to enqueue local job task to RQ",
            error_code="RQ_ENQUEUE_FAILED",
            status_code=503,
            stage="TASKS",
            details={"cause": str(exc), "job_id": job_id},
        ) from exc
