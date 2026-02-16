from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from app.models import Dataset
from app.services.export import export_plan_pdf, generate_map_png
from app.services.geocoding import geocode_dataset
from app.services.jobs import set_job_status
from app.services.optimization import OptimizationPayload, optimize_dataset
from app.utils.db import SessionLocal
from app.utils.errors import AppError


EXPORT_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "exports"
EXPORT_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _progress(job_id: str) -> Callable[[int, str], None]:
    def _emit(progress: int, message: str) -> None:
        db = SessionLocal()
        try:
            try:
                set_job_status(db, job_id=job_id, status="RUNNING", progress=progress, message=message)
            except Exception:
                db.rollback()
        finally:
            db.close()

    return _emit


def _run_geocode(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    db = SessionLocal()
    try:
        dataset_id = int(payload["dataset_id"])
        dataset = db.get(Dataset, dataset_id)
        if dataset is not None:
            dataset.status = "GEOCODING_RUNNING"
            db.commit()
        failed_only = bool(payload.get("failed_only", False))
        force_all = bool(payload.get("force_all", False))
        return geocode_dataset(db, dataset_id, failed_only=failed_only, force_all=force_all, progress_cb=_progress(job_id))
    finally:
        db.close()


def _run_optimize(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    db = SessionLocal()
    try:
        dataset_id = int(payload["dataset_id"])
        dataset = db.get(Dataset, dataset_id)
        if dataset is not None:
            dataset.status = "OPTIMIZATION_RUNNING"
            db.commit()
        optimize_payload = OptimizationPayload(
            depot_lat=float(payload["depot_lat"]),
            depot_lon=float(payload["depot_lon"]),
            num_vehicles=int(payload["num_vehicles"]),
            capacity=int(payload["capacity"]) if payload.get("capacity") is not None else None,
            workday_start=str(payload["workday_start"]),
            workday_end=str(payload["workday_end"]),
            solver_time_limit_s=int(payload["solver_time_limit_s"]),
            allow_drop_visits=bool(payload["allow_drop_visits"]),
        )
        return optimize_dataset(db, dataset_id, optimize_payload, progress_cb=_progress(job_id))
    finally:
        db.close()


def _run_export_pdf(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    db = SessionLocal()
    try:
        plan_id = int(payload["plan_id"])
        profile = str(payload.get("profile", "driver"))
        vehicle_idx = payload.get("vehicle_idx")
        vehicle = int(vehicle_idx) if vehicle_idx is not None else None
        _progress(job_id)(20, "Rendering PDF")
        pdf_bytes = export_plan_pdf(db, plan_id, profile=profile, vehicle_idx=vehicle)
        out_name = f"plan_{plan_id}_{profile}{f'_v{vehicle}' if vehicle is not None else ''}.pdf"
        out_path = EXPORT_CACHE_DIR / out_name
        out_path.write_bytes(pdf_bytes)
        _progress(job_id)(100, "PDF export ready")
        return {"plan_id": plan_id, "format": "pdf", "file_path": str(out_path)}
    finally:
        db.close()


def _run_map_png(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    db = SessionLocal()
    try:
        plan_id = int(payload["plan_id"])
        route_id = payload.get("route_id")
        mode = str(payload.get("mode", "all"))
        _progress(job_id)(20, "Generating map image")
        png = generate_map_png(db, plan_id, route_id=int(route_id) if route_id is not None else None, mode=mode, progress_cb=_progress(job_id))
        out_name = f"plan_{plan_id}_{mode}{f'_r{route_id}' if route_id is not None else ''}.png"
        out_path = EXPORT_CACHE_DIR / out_name
        out_path.write_bytes(png)
        _progress(job_id)(100, "Map image ready")
        return {"plan_id": plan_id, "format": "png", "file_path": str(out_path)}
    finally:
        db.close()


def _run_ml_train(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.ml_ops import train_and_register_model

    db = SessionLocal()
    try:
        result = train_and_register_model(db, dataset_path=payload.get("dataset_path"), progress_cb=_progress(job_id))
        _progress(job_id)(100, "Model training complete")
        return result
    finally:
        db.close()


def _run_ml_monitor(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.ml_ops import compute_latest_ml_metrics

    db = SessionLocal()
    try:
        result = compute_latest_ml_metrics(db, persist_monitoring=True)
        _progress(job_id)(100, "ML monitoring complete")
        return result
    finally:
        db.close()


def _run_ml_retrain_if_needed(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.ml_ops import retrain_if_needed

    db = SessionLocal()
    try:
        result = retrain_if_needed(db, progress_cb=_progress(job_id))
        _progress(job_id)(100, "Retrain job finished")
        return result
    finally:
        db.close()


def run_job(*, job_id: str, job_type: str, payload: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        set_job_status(db, job_id=job_id, status="RUNNING", progress=1, message="Started")
    finally:
        db.close()

    try:
        if job_type == "GEOCODE_DATASET":
            result = _run_geocode(job_id, payload)
        elif job_type == "OPTIMIZE_DATASET":
            result = _run_optimize(job_id, payload)
        elif job_type == "EXPORT_PDF":
            result = _run_export_pdf(job_id, payload)
        elif job_type == "GENERATE_MAP_PNG":
            result = _run_map_png(job_id, payload)
        elif job_type == "ML_TRAIN":
            result = _run_ml_train(job_id, payload)
        elif job_type == "ML_MONITOR":
            result = _run_ml_monitor(job_id, payload)
        elif job_type == "ML_RETRAIN_IF_NEEDED":
            result = _run_ml_retrain_if_needed(job_id, payload)
        else:
            raise AppError(message=f"Unsupported job type: {job_type}", error_code="JOB_TYPE_UNSUPPORTED", status_code=400)

        db = SessionLocal()
        try:
            set_job_status(db, job_id=job_id, status="SUCCEEDED", progress=100, message="Completed", result_ref=result)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        db = SessionLocal()
        try:
            message = str(exc)
            result_ref = {"error": message}
            if isinstance(exc, AppError) and exc.details is not None:
                result_ref["details"] = exc.details
            set_job_status(db, job_id=job_id, status="FAILED", progress=100, message=message, result_ref=result_ref)
        finally:
            db.close()
        raise
