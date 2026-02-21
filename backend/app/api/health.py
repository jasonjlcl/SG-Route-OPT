from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.services.cloud_tasks import cloud_tasks_enabled
from app.services.ml_ops import latest_monitoring_snapshot
from app.services.storage import gcs_enabled
from app.utils.db import engine
from app.utils.db import SessionLocal
from app.utils.settings import get_settings

router = APIRouter(tags=["health"])


def _check_database_ready() -> dict[str, Any]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unready", "detail": str(exc)}


def _check_cloud_tasks_ready() -> dict[str, Any]:
    settings = get_settings()
    if not settings.is_cloud_mode:
        return {"status": "skipped", "detail": "cloud mode disabled"}

    if not cloud_tasks_enabled():
        return {"status": "unready", "detail": "Cloud Tasks is not configured"}
    return {
        "status": "ready",
        "queue": settings.cloud_tasks_queue,
        "detail": "Cloud Tasks client/config is available",
    }


def _check_gcs_ready() -> dict[str, Any]:
    settings = get_settings()
    if not settings.is_cloud_mode:
        return {"status": "skipped", "detail": "cloud mode disabled"}
    if not settings.gcs_bucket:
        return {"status": "unready", "detail": "GCS bucket is not configured"}
    if not gcs_enabled():
        return {"status": "unready", "detail": "GCS client is unavailable or misconfigured"}

    bucket_name = settings.gcs_bucket.replace("gs://", "").strip("/")
    return {
        "status": "ready",
        "bucket": bucket_name,
        "detail": "GCS client/config is available",
    }


def _build_readiness_report() -> dict[str, Any]:
    checks = {
        "database": _check_database_ready(),
        "cloud_tasks": _check_cloud_tasks_ready(),
        "gcs": _check_gcs_ready(),
    }
    ready = all(check["status"] in {"ready", "skipped"} for check in checks.values())
    return {"status": "ok" if ready else "degraded", "ready": ready, "checks": checks}


@router.get("/api/v1/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    monitoring = {}
    db = SessionLocal()
    try:
        monitoring = latest_monitoring_snapshot(db)
    except Exception:
        monitoring = {}
    finally:
        db.close()
    return {
        "status": "ok",
        "env": settings.app_env,
        "ml_needs_retrain": bool(monitoring.get("needs_retrain", False)),
        "feature_google_traffic": bool(settings.feature_google_traffic),
        "feature_ml_uplift": bool(settings.feature_ml_uplift),
        "feature_eval_dashboard": bool(settings.feature_eval_dashboard),
    }


@router.get("/health/live")
def health_live() -> dict[str, Any]:
    settings = get_settings()
    return {"status": "ok", "env": settings.app_env}


@router.get("/health/ready")
def health_ready() -> JSONResponse:
    report = _build_readiness_report()
    status_code = 200 if report["ready"] else 503
    return JSONResponse(status_code=status_code, content=report)
