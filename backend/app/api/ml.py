from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.schemas.api import JobAcceptedResponse
from app.services.ml_evaluation import compare_baseline_vs_model
from app.services.jobs import create_job, enqueue_job
from app.services.ml_ops import (
    compute_latest_ml_metrics,
    generate_drift_report,
    get_latest_rollout,
    latest_monitoring_snapshot,
    list_models,
    set_rollout,
    upload_actuals_csv,
)
from app.utils.settings import get_settings
from app.utils.db import get_db

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])


def _verify_scheduler_token(x_scheduler_token: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if settings.app_env == "test":
        return
    if not settings.scheduler_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Scheduler token is not configured")
    if x_scheduler_token != settings.scheduler_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid scheduler token")


@router.get("/models")
def get_models(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {
        "models": list_models(db),
        "rollout": get_latest_rollout(db),
    }


@router.post("/models/train")
def train_model(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> dict:
    dataset_path = payload.get("dataset_path") if payload else None
    force_vertex = bool(payload.get("force_vertex")) if payload else False
    job = create_job(
        db,
        job_type="ML_TRAIN",
        payload={"dataset_path": dataset_path, "force_vertex": force_vertex},
    )
    enqueue_job(job)
    return JobAcceptedResponse(job_id=job.id, type=job.type).model_dump()


@router.post("/models/train/vertex")
def train_model_vertex(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> dict:
    dataset_path = payload.get("dataset_path") if payload else None
    job = create_job(
        db,
        job_type="ML_TRAIN",
        payload={"dataset_path": dataset_path, "force_vertex": True},
    )
    enqueue_job(job)
    return JobAcceptedResponse(job_id=job.id, type=job.type).model_dump()


@router.post("/rollout")
def update_rollout(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    return set_rollout(
        db,
        active_version=str(payload["active_version"]),
        canary_version=payload.get("canary_version"),
        canary_percent=int(payload.get("canary_percent", 0)),
        enabled=bool(payload.get("enabled", False)),
    )


@router.get("/config")
def get_ml_config(db: Session = Depends(get_db)) -> dict[str, Any]:
    rollout = get_latest_rollout(db) or {}
    settings = get_settings()
    return {
        "active_model_version": rollout.get("active_version"),
        "canary_model_version": rollout.get("canary_version"),
        "canary_percent": rollout.get("canary_percent", 0),
        "canary_enabled": rollout.get("enabled", False),
        "feature_vertex_ai": settings.feature_vertex_ai,
        "feature_vertex_batch_override": settings.feature_vertex_batch_override,
    }


@router.post("/config")
def update_ml_config(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    updated = set_rollout(
        db,
        active_version=str(payload["active_model_version"]),
        canary_version=payload.get("canary_model_version"),
        canary_percent=int(payload.get("canary_percent", 0)),
        enabled=bool(payload.get("canary_enabled", False)),
    )
    settings = get_settings()
    return {
        "active_model_version": updated.get("active_version"),
        "canary_model_version": updated.get("canary_version"),
        "canary_percent": updated.get("canary_percent", 0),
        "canary_enabled": updated.get("enabled", False),
        "feature_vertex_ai": settings.feature_vertex_ai,
        "feature_vertex_batch_override": settings.feature_vertex_batch_override,
    }


@router.post("/actuals/upload")
async def upload_actuals(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    content = await file.read()
    result = upload_actuals_csv(db, filename=file.filename or "actuals.csv", content=content)
    return result


@router.get("/metrics/latest")
def latest_metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    return latest_monitoring_snapshot(db)


@router.get("/evaluation/compare")
def evaluation_compare(
    days: int = 30,
    limit: int = 5000,
    model_version: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return compare_baseline_vs_model(db, days=days, limit=limit, model_version=model_version)


@router.post("/evaluation/run")
def evaluation_run(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> dict:
    body = payload or {}
    job = create_job(
        db,
        job_type="ML_EVALUATION",
        payload={
            "days": int(body.get("days", 30)),
            "limit": int(body.get("limit", 5000)),
            "model_version": body.get("model_version"),
        },
    )
    enqueue_job(job)
    return JobAcceptedResponse(job_id=job.id, type=job.type).model_dump()


@router.post("/metrics/compute")
def compute_metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    job = create_job(db, job_type="ML_MONITOR", payload={})
    enqueue_job(job)
    return JobAcceptedResponse(job_id=job.id, type=job.type).model_dump()


@router.post("/drift-report")
def run_drift_report(
    trigger_retrain: bool = True,
    _: None = Depends(_verify_scheduler_token),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    report = generate_drift_report(db)
    retrain_job_id = None
    if trigger_retrain and report.get("retrain_recommended"):
        retrain_job = create_job(db, job_type="ML_RETRAIN_IF_NEEDED", payload={"trigger": "drift_report"})
        enqueue_job(retrain_job)
        retrain_job_id = retrain_job.id
    return {
        "report": report,
        "triggered_retrain_job_id": retrain_job_id,
    }


@router.get("/health")
def ml_health(db: Session = Depends(get_db)) -> dict[str, Any]:
    metrics = compute_latest_ml_metrics(db, persist_monitoring=False)
    return {
        "status": "ok",
        "needs_retrain": metrics.get("needs_retrain", False),
        "drift_score": metrics.get("drift_score"),
        "mae": metrics.get("mae"),
        "mape": metrics.get("mape"),
    }
