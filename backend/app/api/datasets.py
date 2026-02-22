from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.schemas.api import (
    DatasetSummaryResponse,
    DatasetUploadResponse,
    JobAcceptedResponse,
    OptimizeExperimentRequest,
    OptimizeRequest,
    OptimizeResponse,
    StopsPageResponse,
)
from app.services.datasets import (
    create_dataset_from_upload,
    dataset_summary,
    get_validation_error_log_csv,
    list_stops,
)
from app.services.geocoding import geocode_dataset
from app.services.job_pipeline import create_optimize_pipeline_job
from app.services.jobs import create_job, enqueue_job
from app.services.optimization import OptimizationPayload, optimize_dataset
from app.services.scale_guardrails import validate_optimize_request_scale
from app.utils.db import get_db

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])


@router.post("/upload", response_model=DatasetUploadResponse)
async def upload_dataset(
    file: UploadFile = File(...),
    exclude_invalid: bool = Form(default=False),
    db: Session = Depends(get_db),
) -> DatasetUploadResponse:
    content = await file.read()
    dataset, result, next_action = create_dataset_from_upload(
        db,
        filename=file.filename or "upload.csv",
        content=content,
        exclude_invalid=exclude_invalid,
    )
    return DatasetUploadResponse(
        dataset_id=dataset.id,
        validation_summary={
            "valid_rows_count": result.valid_rows_count,
            "invalid_rows_count": result.invalid_rows_count,
            "invalid_rows": [{"row_index": r.row_index, "reason": r.reason} for r in result.invalid_rows],
        },
        next_action=next_action,
    )


@router.get("/{dataset_id}", response_model=DatasetSummaryResponse)
def get_dataset(dataset_id: int, db: Session = Depends(get_db)) -> DatasetSummaryResponse:
    return DatasetSummaryResponse(**dataset_summary(db, dataset_id))


@router.get("/{dataset_id}/stops", response_model=StopsPageResponse)
def get_dataset_stops(
    dataset_id: int,
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> StopsPageResponse:
    return StopsPageResponse(**list_stops(db, dataset_id, status=status, page=page, page_size=page_size))


@router.post("/{dataset_id}/geocode")
def run_geocoding(
    dataset_id: int,
    failed_only: bool = Query(default=False),
    force_all: bool = Query(default=False),
    sync: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    if sync:
        return geocode_dataset(db, dataset_id, failed_only=failed_only, force_all=force_all)

    job = create_job(
        db,
        job_type="GEOCODE",
        payload={"dataset_id": dataset_id, "failed_only": failed_only, "force_all": force_all},
    )
    enqueue_job(job)
    return JobAcceptedResponse(job_id=job.id, type=job.type).model_dump()


@router.get("/{dataset_id}/error-log")
def download_validation_error_log(dataset_id: int, db: Session = Depends(get_db)) -> PlainTextResponse:
    csv_data = get_validation_error_log_csv(db, dataset_id)
    headers = {"Content-Disposition": f"attachment; filename=dataset_{dataset_id}_validation_errors.csv"}
    return PlainTextResponse(content=csv_data, media_type="text/csv", headers=headers)


@router.post("/{dataset_id}/optimize")
def optimize(
    dataset_id: int,
    payload: OptimizeRequest,
    sync: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    validate_optimize_request_scale(db, dataset_id=dataset_id)

    if sync:
        result = optimize_dataset(
            db,
            dataset_id,
            OptimizationPayload(
                depot_lat=payload.depot_lat,
                depot_lon=payload.depot_lon,
                num_vehicles=payload.fleet.num_vehicles,
                capacity=payload.fleet.capacity,
                workday_start=payload.workday_start,
                workday_end=payload.workday_end,
                solver_time_limit_s=payload.solver.solver_time_limit_s,
                allow_drop_visits=payload.solver.allow_drop_visits,
                use_live_traffic=payload.use_live_traffic,
            ),
        )
        return OptimizeResponse(**result).model_dump()

    job = create_optimize_pipeline_job(
        db,
        dataset_id=dataset_id,
        depot_lat=payload.depot_lat,
        depot_lon=payload.depot_lon,
        num_vehicles=payload.fleet.num_vehicles,
        capacity=payload.fleet.capacity,
        workday_start=payload.workday_start,
        workday_end=payload.workday_end,
        solver_time_limit_s=payload.solver.solver_time_limit_s,
        allow_drop_visits=payload.solver.allow_drop_visits,
        use_live_traffic=payload.use_live_traffic,
    )
    return JobAcceptedResponse(job_id=job.id, type=job.type).model_dump()


@router.post("/{dataset_id}/optimize/ab-test")
def optimize_ab_test(
    dataset_id: int,
    payload: OptimizeExperimentRequest,
    db: Session = Depends(get_db),
) -> dict:
    validate_optimize_request_scale(db, dataset_id=dataset_id)

    job = create_job(
        db,
        job_type="OPTIMIZE_AB_SIMULATION",
        payload={
            "dataset_id": dataset_id,
            "depot_lat": payload.depot_lat,
            "depot_lon": payload.depot_lon,
            "num_vehicles": payload.fleet.num_vehicles,
            "capacity": payload.fleet.capacity,
            "workday_start": payload.workday_start,
            "workday_end": payload.workday_end,
            "solver_time_limit_s": payload.solver.solver_time_limit_s,
            "allow_drop_visits": payload.solver.allow_drop_visits,
            "model_version": payload.model_version,
        },
    )
    enqueue_job(job)
    return JobAcceptedResponse(job_id=job.id, type=job.type).model_dump()
