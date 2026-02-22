from __future__ import annotations

import json
from datetime import datetime
import logging
import time
import uuid
from typing import Any, Callable

from sqlalchemy.exc import OperationalError

from app.models import Dataset, Route
from app.services.cloud_tasks import enqueue_step_task
from app.services.export import export_plan_pdf, generate_map_png
from app.services.geocoding import geocode_dataset
from app.services.jobs import (
    complete_step,
    create_job,
    fail_step,
    get_job_or_404,
    get_steps_state,
    has_step_lock,
    lock_step,
    parse_payload,
    parse_result_ref,
    set_job_status,
    touch_step_lease,
)
from app.services.ml_features import build_feature_dict
from app.services.ml_ops import get_latest_rollout, get_model_metadata
from app.services.optimization import (
    OptimizationPayload,
    build_optimization_matrix_artifact,
    load_matrix_artifact,
    save_matrix_artifact,
    solve_optimization_from_artifact,
)
from app.services.storage import download_bytes, signed_download_url, upload_bytes
from app.services.vertex_ai import run_vertex_batch_prediction
from app.utils.db import SessionLocal
from app.utils.errors import AppError
from app.utils.settings import get_settings

LOGGER = logging.getLogger(__name__)


PIPELINE_STEPS = ["GEOCODE", "BUILD_MATRIX", "OPTIMIZE", "GENERATE_EXPORTS"]
NEXT_STEP = {
    "GEOCODE": "BUILD_MATRIX",
    "BUILD_MATRIX": "OPTIMIZE",
    "OPTIMIZE": "GENERATE_EXPORTS",
    "GENERATE_EXPORTS": None,
}
STEP_PROGRESS_RANGE = {
    "GEOCODE": (1, 25),
    "BUILD_MATRIX": (26, 65),
    "OPTIMIZE": (66, 90),
    "GENERATE_EXPORTS": (91, 100),
}


class InjectedRetryDrillError(RuntimeError):
    """Synthetic failure to force Cloud Tasks redelivery during retry drills."""


def _init_steps_state() -> dict[str, dict[str, Any]]:
    return {step: {"status": "PENDING"} for step in PIPELINE_STEPS}


def _payload_to_optimization_payload(payload: dict[str, Any]) -> OptimizationPayload:
    return OptimizationPayload(
        depot_lat=float(payload["depot_lat"]),
        depot_lon=float(payload["depot_lon"]),
        num_vehicles=int(payload["num_vehicles"]),
        capacity=int(payload["capacity"]) if payload.get("capacity") is not None else None,
        workday_start=str(payload["workday_start"]),
        workday_end=str(payload["workday_end"]),
        solver_time_limit_s=int(payload.get("solver_time_limit_s", 20)),
        allow_drop_visits=bool(payload.get("allow_drop_visits", True)),
        use_live_traffic=bool(payload.get("use_live_traffic", False)),
    )


def _merge_result(db, *, job_id: str, partial: dict[str, Any]) -> None:
    job = get_job_or_404(db, job_id)
    current = parse_result_ref(job) or {}
    current.update(partial)
    set_job_status(
        db,
        job_id=job_id,
        status=job.status,
        progress_pct=job.progress_pct,
        current_step=job.current_step,
        message=job.message,
        result_ref=current,
    )


def _progress_emitter(job_id: str, step: str, *, lock_token: str) -> Callable[[int, str], None]:
    start, end = STEP_PROGRESS_RANGE[step]

    def _emit(inner_progress: int, message: str) -> None:
        mapped = start + int((max(0, min(100, inner_progress)) / 100) * (end - start))
        for attempt in range(3):
            db = SessionLocal()
            try:
                if not touch_step_lease(db, job_id=job_id, step=step, lock_token=lock_token):
                    return
                set_job_status(
                    db,
                    job_id=job_id,
                    status="RUNNING",
                    progress_pct=mapped,
                    current_step=step,
                    message=message,
                )
                return
            except OperationalError as exc:
                detail = str(exc).lower()
                if "database is locked" in detail:
                    if attempt < 2:
                        time.sleep(0.05)
                        continue
                    # Preserve pipeline execution even if progress writes contend on SQLite.
                    return
                raise
            finally:
                db.close()

    return _emit


def _maybe_inject_retry_drill(db, *, job_id: str, step: str) -> None:
    settings = get_settings()
    configured_step = str(settings.pipeline_retry_drill_step or "").strip().upper()
    delay_seconds = max(0, int(settings.pipeline_retry_drill_delay_seconds or 0))
    if not configured_step or configured_step != step or delay_seconds <= 0:
        return
    if not settings.is_cloud_mode:
        return

    job = get_job_or_404(db, job_id)
    steps = get_steps_state(job)
    entry = steps.get(step)
    if not isinstance(entry, dict):
        return
    if bool(entry.get("retry_drill_injected")):
        return

    entry["retry_drill_injected"] = True
    entry["retry_drill_injected_at"] = datetime.utcnow().isoformat()
    job.steps_json = json.dumps(steps)
    db.commit()
    time.sleep(delay_seconds)
    raise InjectedRetryDrillError(f"Injected retry drill abort for step={step}")


def create_optimize_pipeline_job(
    db,
    *,
    dataset_id: int,
    depot_lat: float,
    depot_lon: float,
    num_vehicles: int,
    capacity: int | None,
    workday_start: str,
    workday_end: str,
    solver_time_limit_s: int,
    allow_drop_visits: bool,
    use_live_traffic: bool = False,
) -> Any:
    payload = {
        "dataset_id": dataset_id,
        "depot_lat": depot_lat,
        "depot_lon": depot_lon,
        "num_vehicles": num_vehicles,
        "capacity": capacity,
        "workday_start": workday_start,
        "workday_end": workday_end,
        "solver_time_limit_s": solver_time_limit_s,
        "allow_drop_visits": allow_drop_visits,
        "use_live_traffic": bool(use_live_traffic),
    }
    job = create_job(db, job_type="OPTIMIZE", payload=payload)
    job.steps_json = json.dumps(_init_steps_state())
    db.commit()
    db.refresh(job)

    set_job_status(
        db,
        job_id=job.id,
        status="QUEUED",
        progress_pct=0,
        current_step="GEOCODE",
        message="Queued for geocoding",
    )
    enqueue_step_task(job_id=job.id, step="GEOCODE")
    return job


def _run_geocode_step(*, job_id: str, payload: dict[str, Any], lock_token: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        dataset_id = int(payload["dataset_id"])
        dataset = db.get(Dataset, dataset_id)
        if dataset is not None:
            dataset.status = "GEOCODING_RUNNING"
            db.commit()
        result = geocode_dataset(
            db,
            dataset_id,
            failed_only=False,
            force_all=False,
            progress_cb=_progress_emitter(job_id, "GEOCODE", lock_token=lock_token),
        )
        return {"geocode": result}
    finally:
        db.close()


def _apply_vertex_batch_if_enabled(db, *, job_id: str, artifact: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.feature_vertex_ai:
        return {"vertex_batch_used": False, "reason": "feature_flag_disabled"}

    rollout = get_latest_rollout(db) or {}
    active_version = rollout.get("active_version")
    if not active_version:
        return {"vertex_batch_used": False, "reason": "no_active_model"}

    metadata = get_model_metadata(db, str(active_version))
    if not metadata:
        return {"vertex_batch_used": False, "reason": "active_model_missing"}

    model_resource = metadata.get("vertex_model_resource")
    if not model_resource:
        return {"vertex_batch_used": False, "reason": "vertex_model_not_registered"}

    nodes = artifact.get("nodes", [])
    distance_matrix = artifact.get("distance_matrix_m", [])
    base_duration_matrix = artifact.get("base_duration_matrix_s", [])
    if not nodes or not distance_matrix or not base_duration_matrix:
        return {"vertex_batch_used": False, "reason": "artifact_missing_features"}

    depart_bucket = str(artifact.get("depart_bucket") or "08:00")
    day_parts = depart_bucket.split(":")
    try:
        depart_dt = datetime.utcnow().replace(
            hour=int(day_parts[0]),
            minute=int(day_parts[1]),
            second=0,
            microsecond=0,
        )
    except Exception:
        depart_dt = datetime.utcnow().replace(hour=8, minute=0, second=0, microsecond=0)

    unique_rows: list[dict[str, Any]] = []
    unique_keys: list[tuple[Any, ...]] = []
    pair_to_bucket: dict[tuple[int, int], tuple[Any, ...]] = {}
    key_to_row_idx: dict[tuple[Any, ...], int] = {}
    day_of_week = int(artifact.get("day_of_week") or depart_dt.weekday())
    for i in range(len(nodes)):
        for j in range(len(nodes)):
            if i == j:
                continue
            origin = nodes[i]
            dest = nodes[j]
            distance_m = float(distance_matrix[i][j])
            bucket_key = (
                round(float(origin["lat"]), 2),
                round(float(origin["lon"]), 2),
                round(float(dest["lat"]), 2),
                round(float(dest["lon"]), 2),
                depart_bucket,
                day_of_week,
                int(distance_m // 1000),
            )
            pair_to_bucket[(i, j)] = bucket_key
            if bucket_key in key_to_row_idx:
                continue
            features = build_feature_dict(
                base_duration_s=float(base_duration_matrix[i][j]),
                distance_m=distance_m,
                depart_dt=depart_dt,
                origin_lat=float(origin["lat"]),
                origin_lon=float(origin["lon"]),
                dest_lat=float(dest["lat"]),
                dest_lon=float(dest["lon"]),
            )
            key_to_row_idx[bucket_key] = len(unique_rows)
            unique_keys.append(bucket_key)
            unique_rows.append(features)

    predictions = run_vertex_batch_prediction(
        model_resource=str(model_resource),
        rows=unique_rows,
        job_key=f"{job_id}-matrix",
    )
    if not predictions or len(predictions) != len(unique_keys):
        return {"vertex_batch_used": False, "reason": "batch_prediction_unavailable"}

    pred_by_bucket = {unique_keys[idx]: float(predictions[idx]) for idx in range(len(unique_keys))}
    for (i, j), bucket_key in pair_to_bucket.items():
        pred = pred_by_bucket.get(bucket_key)
        if pred is None:
            continue
        artifact["duration_matrix_s"][i][j] = max(1, int(round(float(pred))))
    artifact["chosen_model_version"] = str(active_version)
    artifact["vertex_batch_used"] = True
    artifact["vertex_model_resource"] = str(model_resource)
    artifact["vertex_bucket_cache_size"] = len(unique_keys)
    return {"vertex_batch_used": True, "model_version": str(active_version), "bucket_cache_size": len(unique_keys)}


def _run_build_matrix_step(*, job_id: str, payload: dict[str, Any], lock_token: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        dataset_id = int(payload["dataset_id"])
        optimization_payload = _payload_to_optimization_payload(payload)
        artifact = build_optimization_matrix_artifact(
            db,
            dataset_id=dataset_id,
            payload=optimization_payload,
            progress_cb=_progress_emitter(job_id, "BUILD_MATRIX", lock_token=lock_token),
        )
        vertex_meta = _apply_vertex_batch_if_enabled(db, job_id=job_id, artifact=artifact)
        artifact_path = save_matrix_artifact(dataset_id=dataset_id, job_id=job_id, artifact=artifact)
        artifact_bytes = json.dumps(artifact).encode("utf-8")
        upload = upload_bytes(
            object_path=f"matrix/{job_id}.json",
            payload=artifact_bytes,
            content_type="application/json",
        )
        return {
            "matrix_artifact_path": artifact_path,
            "matrix_artifact_ref": upload,
            "model_version": artifact.get("chosen_model_version"),
            "vertex": vertex_meta,
        }
    finally:
        db.close()


def _load_matrix_artifact_for_optimize(*, result_ref: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    artifact_ref = result_ref.get("matrix_artifact_ref")

    if isinstance(artifact_ref, dict):
        object_path = str(artifact_ref.get("object_path") or "").strip()
        if object_path:
            try:
                payload = download_bytes(object_path=object_path)
                if payload is not None:
                    return json.loads(payload.decode("utf-8"))
                errors.append(f"object_path_not_found:{object_path}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"object_path_read_failed:{object_path}:{exc}")

        file_path = str(artifact_ref.get("file_path") or "").strip()
        if file_path:
            try:
                return load_matrix_artifact(file_path)
            except AppError as exc:
                errors.append(f"file_path_load_failed:{file_path}:{exc.error_code}")

    artifact_path = str(result_ref.get("matrix_artifact_path") or "").strip()
    if artifact_path:
        try:
            return load_matrix_artifact(artifact_path)
        except AppError as exc:
            errors.append(f"matrix_path_load_failed:{artifact_path}:{exc.error_code}")

    if not errors:
        raise AppError(
            message="Matrix artifact missing for OPTIMIZE step",
            error_code="MATRIX_ARTIFACT_MISSING",
            status_code=500,
            stage="OPTIMIZATION",
        )

    raise AppError(
        message="Matrix artifact could not be loaded for OPTIMIZE step",
        error_code="MATRIX_ARTIFACT_LOAD_FAILED",
        status_code=500,
        stage="OPTIMIZATION",
        details={"attempts": errors},
    )


def _run_optimize_step(
    *,
    job_id: str,
    payload: dict[str, Any],
    result_ref: dict[str, Any],
    lock_token: str,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        dataset = db.get(Dataset, int(payload["dataset_id"]))
        if dataset is not None:
            dataset.status = "OPTIMIZATION_RUNNING"
            db.commit()

        artifact = _load_matrix_artifact_for_optimize(result_ref=result_ref)
        optimize_payload = _payload_to_optimization_payload(payload)
        optimize_result = solve_optimization_from_artifact(
            db,
            dataset_id=int(payload["dataset_id"]),
            payload=optimize_payload,
            artifact=artifact,
            progress_cb=_progress_emitter(job_id, "OPTIMIZE", lock_token=lock_token),
        )
        return {"optimize": optimize_result, "plan_id": optimize_result.get("plan_id")}
    finally:
        db.close()


def _run_generate_exports_step(*, job_id: str, result_ref: dict[str, Any], lock_token: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        optimize_result = result_ref.get("optimize") or {}
        if isinstance(optimize_result, dict) and optimize_result.get("feasible") is False:
            return {"exports_skipped": True, "reason": "plan_infeasible"}

        plan_id = int((optimize_result or {}).get("plan_id") or result_ref.get("plan_id") or 0)
        if plan_id <= 0:
            raise AppError(
                message="No plan_id found for export generation",
                error_code="PLAN_NOT_READY",
                status_code=500,
                stage="EXPORT",
            )

        route_rows = db.query(Route).filter(Route.plan_id == plan_id).all()
        map_results: list[dict[str, Any]] = []
        step_progress = _progress_emitter(job_id, "GENERATE_EXPORTS", lock_token=lock_token)
        total_routes = max(1, len(route_rows))

        for idx, route in enumerate(route_rows):
            step_progress(int((idx / total_routes) * 70), f"Rendering map image for vehicle {route.vehicle_idx}")
            png = generate_map_png(db, plan_id, route_id=route.id, mode="single")
            upload = upload_bytes(
                object_path=f"maps/{plan_id}/{route.id}.png",
                payload=png,
                content_type="image/png",
            )
            map_results.append(
                {
                    "route_id": route.id,
                    "vehicle_idx": route.vehicle_idx,
                    **upload,
                    "signed_url": signed_download_url(object_path=f"maps/{plan_id}/{route.id}.png"),
                }
            )

        step_progress(80, "Generating driver pack PDF")
        pdf = export_plan_pdf(db, plan_id, profile="driver")
        pdf_upload = upload_bytes(
            object_path=f"driver_packs/{plan_id}/driver_pack.pdf",
            payload=pdf,
            content_type="application/pdf",
        )
        pdf_signed_url = signed_download_url(object_path=f"driver_packs/{plan_id}/driver_pack.pdf")
        step_progress(100, "Export artifacts ready")

        return {
            "maps": map_results,
            "driver_pack": {
                **pdf_upload,
                "signed_url": pdf_signed_url,
            },
            "file_path": pdf_upload.get("file_path"),
        }
    finally:
        db.close()


def process_task_payload(task_payload: dict[str, Any]) -> None:
    job_id = str(task_payload.get("job_id") or "")
    step = str(task_payload.get("step") or "")
    if not job_id or not step:
        return
    if step not in PIPELINE_STEPS:
        return

    lock_token = f"{step}:{uuid.uuid4().hex}"
    db = SessionLocal()
    try:
        job = get_job_or_404(db, job_id)
        if job.type != "OPTIMIZE":
            return
        if job.status in {"SUCCEEDED", "FAILED", "CANCELED", "CANCELLED"}:
            return

        if not lock_step(db, job_id=job_id, step=step, lock_token=lock_token):
            # If step already completed but downstream is pending, enqueue next to recover chain.
            job = get_job_or_404(db, job_id)
            steps = get_steps_state(job)
            step_state = (steps.get(step) or {}).get("status")
            next_step = NEXT_STEP.get(step)
            next_state = (steps.get(next_step) or {}).get("status") if next_step else None
            if step_state == "SUCCEEDED" and next_step and next_state in {None, "PENDING"}:
                enqueue_step_task(job_id=job_id, step=next_step)
            elif step_state == "SUCCEEDED" and next_step is None and job.status != "SUCCEEDED":
                set_job_status(
                    db,
                    job_id=job_id,
                    status="SUCCEEDED",
                    progress_pct=100,
                    current_step=step,
                    message="All optimization steps completed",
                    result_ref=parse_result_ref(job) or {},
                )
            return

        set_job_status(
            db,
            job_id=job_id,
            status="RUNNING",
            progress_pct=max(job.progress_pct, STEP_PROGRESS_RANGE[step][0]),
            current_step=step,
            message=f"Running {step}",
        )
        _maybe_inject_retry_drill(db, job_id=job_id, step=step)

        payload = parse_payload(job)
        result_ref = parse_result_ref(job) or {}

        if step == "GEOCODE":
            partial = _run_geocode_step(job_id=job_id, payload=payload, lock_token=lock_token)
        elif step == "BUILD_MATRIX":
            partial = _run_build_matrix_step(job_id=job_id, payload=payload, lock_token=lock_token)
        elif step == "OPTIMIZE":
            partial = _run_optimize_step(job_id=job_id, payload=payload, result_ref=result_ref, lock_token=lock_token)
        elif step == "GENERATE_EXPORTS":
            partial = _run_generate_exports_step(job_id=job_id, result_ref=result_ref, lock_token=lock_token)
        else:
            partial = {}

        if not has_step_lock(db, job_id=job_id, step=step, lock_token=lock_token):
            return

        _merge_result(db, job_id=job_id, partial=partial)
        complete_step(
            db,
            job_id=job_id,
            step=step,
            lock_token=lock_token,
            progress_pct=STEP_PROGRESS_RANGE[step][1],
            message=f"{step} complete",
        )

        next_step = NEXT_STEP.get(step)
        if next_step is not None:
            enqueue_step_task(job_id=job_id, step=next_step)
            return

        latest = get_job_or_404(db, job_id)
        set_job_status(
            db,
            job_id=job_id,
            status="SUCCEEDED",
            progress_pct=100,
            current_step=step,
            message="All optimization steps completed",
            result_ref=parse_result_ref(latest) or {},
        )
        completed = get_job_or_404(db, job_id)
        result_ref = parse_result_ref(completed) or {}
        latency_s = max(0, int((datetime.utcnow() - completed.created_at).total_seconds()))
        warn_threshold_s = int(get_settings().optimize_latency_warn_seconds)
        LOGGER.info(
            "OPTIMIZE_PIPELINE_COMPLETE job_id=%s dataset_id=%s plan_id=%s latency_s=%s",
            job_id,
            payload.get("dataset_id"),
            result_ref.get("plan_id"),
            latency_s,
        )
        if latency_s >= warn_threshold_s:
            LOGGER.warning(
                "OPTIMIZE_LATENCY_SLOW job_id=%s dataset_id=%s plan_id=%s latency_s=%s threshold_s=%s",
                job_id,
                payload.get("dataset_id"),
                result_ref.get("plan_id"),
                latency_s,
                warn_threshold_s,
            )
    except InjectedRetryDrillError:
        raise
    except AppError as exc:
        fail_step(
            db,
            job_id=job_id,
            step=step,
            lock_token=lock_token,
            error_code=exc.error_code,
            error_detail=exc.details or exc.message,
        )
    except Exception as exc:  # noqa: BLE001
        fail_step(
            db,
            job_id=job_id,
            step=step,
            lock_token=lock_token,
            error_code="STEP_EXECUTION_FAILED",
            error_detail=str(exc),
        )
    finally:
        db.close()
