from __future__ import annotations

import traceback
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import datasets, health, plans, stops
from app.models import Base
from app.utils.db import SessionLocal, engine
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


@app.middleware("http")
async def structured_error_middleware(request: Request, call_next):
    correlation_id = str(uuid.uuid4())
    request.state.correlation_id = correlation_id

    try:
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    except AppError as exc:
        db = SessionLocal()
        try:
            log_error(db, exc.stage, exc.message, dataset_id=exc.dataset_id, details=exc.details)
        finally:
            db.close()
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
        db = SessionLocal()
        try:
            log_error(db, "API", str(exc), details={"traceback": traceback.format_exc()})
        finally:
            db.close()
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
