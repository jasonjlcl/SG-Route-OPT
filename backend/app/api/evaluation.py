from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.schemas.api import EvaluationRunRequest, JobAcceptedResponse
from app.services.jobs import create_job, enqueue_job
from app.services.ml_uplift_evaluation import evaluate_prediction_accuracy
from app.utils.db import get_db
from app.utils.settings import get_settings


router = APIRouter(prefix="/api/v1/evaluation", tags=["evaluation"])


def _ensure_eval_enabled() -> None:
    if not get_settings().feature_eval_dashboard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation dashboard feature is disabled",
        )


@router.get("/prediction")
def prediction_metrics(
    limit: int = Query(default=5000, ge=100, le=100000),
    _: None = Depends(_ensure_eval_enabled),
) -> dict[str, Any]:
    return evaluate_prediction_accuracy(limit=limit)


@router.post("/run")
def run_evaluation(
    payload: EvaluationRunRequest,
    _: None = Depends(_ensure_eval_enabled),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    job = create_job(
        db,
        job_type="ML_UPLIFT_EVAL",
        payload={
            "dataset_id": payload.dataset_id,
            "depot_lat": payload.depot_lat,
            "depot_lon": payload.depot_lon,
            "num_vehicles": payload.fleet_config.num_vehicles,
            "capacity": payload.fleet_config.capacity,
            "workday_start": payload.workday_start,
            "workday_end": payload.workday_end,
            "solver_time_limit_s": payload.solver.solver_time_limit_s,
            "allow_drop_visits": payload.solver.allow_drop_visits,
            "sample_limit": payload.sample_limit,
        },
    )
    enqueue_job(job)
    return JobAcceptedResponse(job_id=job.id, type=job.type).model_dump()

