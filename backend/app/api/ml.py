from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.schemas.api import JobAcceptedResponse
from app.services.jobs import create_job, enqueue_job
from app.services.ml_ops import (
    compute_latest_ml_metrics,
    get_latest_rollout,
    latest_monitoring_snapshot,
    list_models,
    set_rollout,
    upload_actuals_csv,
)
from app.utils.db import get_db

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])


@router.get("/models")
def get_models(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {
        "models": list_models(db),
        "rollout": get_latest_rollout(db),
    }


@router.post("/models/train")
def train_model(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> dict:
    dataset_path = payload.get("dataset_path") if payload else None
    job = create_job(
        db,
        job_type="ML_TRAIN",
        payload={"dataset_path": dataset_path},
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


@router.post("/metrics/compute")
def compute_metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    job = create_job(db, job_type="ML_MONITOR", payload={})
    enqueue_job(job)
    return JobAcceptedResponse(job_id=job.id, type=job.type).model_dump()


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

