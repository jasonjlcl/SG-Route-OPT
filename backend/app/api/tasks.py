from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.services.job_pipeline import process_task_payload
from app.utils.settings import get_settings

try:
    from google.auth.transport import requests as grequests
    from google.oauth2 import id_token

    GOOGLE_AUTH_AVAILABLE = True
except Exception:  # noqa: BLE001
    GOOGLE_AUTH_AVAILABLE = False


router = APIRouter(prefix="/tasks", tags=["tasks"])


def _verify_cloud_tasks_oidc(request: Request) -> None:
    settings = get_settings()
    if settings.app_env == "test" or not settings.tasks_auth_required:
        return

    task_name = request.headers.get("X-CloudTasks-TaskName")
    auth_header = request.headers.get("Authorization") or ""
    if not task_name or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Cloud Tasks identity headers")
    if not GOOGLE_AUTH_AVAILABLE:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="google-auth dependency is missing")

    token = auth_header.split(" ", 1)[1].strip()
    audience = settings.cloud_tasks_audience or f"{settings.app_base_url.rstrip('/')}/tasks/handle"

    try:
        info = id_token.verify_oauth2_token(token, grequests.Request(), audience=audience)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Cloud Tasks OIDC token") from exc

    issuer = str(info.get("iss", ""))
    if issuer not in {"https://accounts.google.com", "accounts.google.com"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unexpected OIDC token issuer")

    if settings.cloud_tasks_service_account:
        email = str(info.get("email", ""))
        if email != settings.cloud_tasks_service_account:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unexpected Cloud Tasks principal")


@router.post("/handle")
def handle_task(payload: dict[str, Any], _: None = Depends(_verify_cloud_tasks_oidc)) -> dict[str, Any]:
    process_task_payload(payload)
    return {"ok": True}
