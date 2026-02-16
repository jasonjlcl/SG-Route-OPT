from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from app.utils.settings import get_settings

try:
    from google.cloud import tasks_v2
    from google.protobuf import timestamp_pb2

    CLOUD_TASKS_AVAILABLE = True
except Exception:  # noqa: BLE001
    CLOUD_TASKS_AVAILABLE = False


def cloud_tasks_enabled() -> bool:
    settings = get_settings()
    return bool(
        CLOUD_TASKS_AVAILABLE
        and settings.gcp_project_id
        and settings.gcp_region
        and settings.cloud_tasks_queue
        and settings.app_base_url
    )


def _inline_dispatch(payload: dict[str, Any]) -> None:
    from app.services.job_pipeline import process_task_payload

    process_task_payload(payload)


def enqueue_step_task(*, job_id: str, step: str, delay_seconds: int = 0) -> None:
    payload = {"job_id": job_id, "step": step}
    settings = get_settings()

    if settings.jobs_force_inline:
        _inline_dispatch(payload)
        return

    if not cloud_tasks_enabled():
        thread = threading.Thread(target=_inline_dispatch, args=(payload,), daemon=True)
        thread.start()
        return

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
    except Exception:
        thread = threading.Thread(target=_inline_dispatch, args=(payload,), daemon=True)
        thread.start()
