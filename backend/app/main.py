from __future__ import annotations

import traceback
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import datasets, evaluation, health, jobs, ml, plans, stops, tasks
from app.models import Base
from app.services.scheduler import start_scheduler, stop_scheduler
from app.utils.db import SessionLocal, engine, ensure_schema_compatibility
from app.utils.errors import AppError, log_error
from app.utils.settings import get_settings


settings = get_settings()
app = FastAPI(title="SG Route Optimization API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility()
    start_scheduler()


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_scheduler()


@app.middleware("http")
async def structured_error_middleware(request: Request, call_next):
    correlation_id = str(uuid.uuid4())
    request.state.correlation_id = correlation_id

    try:
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    except AppError as exc:
        _safe_log_error(stage=exc.stage, message=exc.message, dataset_id=exc.dataset_id, details=exc.details)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "correlation_id": correlation_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        _safe_log_error(stage="API", message=str(exc), details={"traceback": traceback.format_exc()})
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "INTERNAL_ERROR",
                "message": "Unexpected server error",
                "details": {"type": type(exc).__name__},
                "correlation_id": correlation_id,
            },
        )


app.include_router(health.router)
app.include_router(datasets.router)
app.include_router(stops.router)
app.include_router(plans.router)
app.include_router(jobs.router)
app.include_router(ml.router)
app.include_router(evaluation.router)
app.include_router(tasks.router)


def _safe_log_error(*, stage: str, message: str, dataset_id: int | None = None, details=None) -> None:
    db = SessionLocal()
    try:
        try:
            log_error(db, stage, message, dataset_id=dataset_id, details=details)
        except Exception:
            # Never allow best-effort error logging to mask/replace the original request failure.
            db.rollback()
    finally:
        db.close()
