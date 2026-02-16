from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Dataset, ErrorLog, Plan, Stop
from app.services.validation import ValidationResult, build_error_log_csv, parse_uploaded_file, validate_rows
from app.utils.errors import AppError, log_error
from app.utils.settings import get_settings


def create_dataset_from_upload(
    db: Session,
    filename: str,
    content: bytes,
    *,
    exclude_invalid: bool,
) -> tuple[Dataset, ValidationResult, str]:
    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise AppError(
            message=f"Upload exceeds MAX_UPLOAD_MB={settings.max_upload_mb}",
            error_code="UPLOAD_TOO_LARGE",
            status_code=400,
            stage="VALIDATION",
        )

    try:
        df = parse_uploaded_file(filename, content)
    except Exception as exc:
        log_error(db, "VALIDATION", str(exc))
        raise

    result = validate_rows(df)

    dataset = Dataset(filename=filename, status="VALIDATED" if result.invalid_rows_count == 0 else "VALIDATION_FAILED")
    db.add(dataset)
    db.flush()

    if result.invalid_rows_count > 0:
        payload = {
            "valid_rows_count": result.valid_rows_count,
            "invalid_rows_count": result.invalid_rows_count,
            "invalid_rows": [{"row_index": i.row_index, "reason": i.reason} for i in result.invalid_rows],
            "error_log_csv": build_error_log_csv(result.invalid_rows),
        }
        db.add(
            ErrorLog(
                dataset_id=dataset.id,
                stage="VALIDATION",
                payload_json=json.dumps(payload),
            )
        )

    if result.valid_rows_count == 0:
        dataset.status = "VALIDATION_FAILED"
        db.commit()
        return dataset, result, "UPLOAD_FIXED_FILE"

    if result.invalid_rows_count > 0 and not exclude_invalid:
        dataset.status = "VALIDATION_FAILED"
        db.commit()
        return dataset, result, "PROCEED_WITH_VALID_STOPS"

    for row in result.valid_rows:
        db.add(
            Stop(
                dataset_id=dataset.id,
                stop_ref=row["stop_ref"],
                address=row["address"],
                postal_code=row["postal_code"],
                demand=row["demand"],
                service_time_min=row["service_time_min"],
                tw_start=row["tw_start"],
                tw_end=row["tw_end"],
                phone=row.get("phone"),
                contact_name=row.get("contact_name"),
                geocode_status="PENDING",
            )
        )

    dataset.status = "READY_FOR_GEOCODING"
    db.commit()
    db.refresh(dataset)
    return dataset, result, "RUN_GEOCODING"


def get_dataset_or_404(db: Session, dataset_id: int) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError(
            message=f"Dataset {dataset_id} not found",
            error_code="NOT_FOUND",
            status_code=404,
        )
    return dataset


def dataset_summary(db: Session, dataset_id: int) -> dict[str, Any]:
    dataset = get_dataset_or_404(db, dataset_id)

    counts = db.execute(
        select(Stop.geocode_status, func.count(Stop.id)).where(Stop.dataset_id == dataset_id).group_by(Stop.geocode_status)
    ).all()

    stop_count = db.execute(select(func.count(Stop.id)).where(Stop.dataset_id == dataset_id)).scalar_one()
    valid_stop_count = stop_count

    geocode_counts = {status: count for status, count in counts}
    geocoded_count = int(geocode_counts.get("SUCCESS", 0)) + int(geocode_counts.get("MANUAL", 0))
    failed_count = int(geocode_counts.get("FAILED", 0))

    latest_validation_log = db.execute(
        select(ErrorLog)
        .where(ErrorLog.dataset_id == dataset_id, ErrorLog.stage == "VALIDATION")
        .order_by(ErrorLog.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    invalid_rows_count = 0
    if latest_validation_log:
        try:
            payload = json.loads(latest_validation_log.payload_json)
            invalid_rows_count = int(payload.get("invalid_rows_count") or 0)
        except Exception:  # noqa: BLE001
            invalid_rows_count = 0

    if valid_stop_count <= 0:
        validation_state = "BLOCKED" if dataset.status == "VALIDATION_FAILED" or invalid_rows_count > 0 else "NOT_STARTED"
    elif invalid_rows_count > 0:
        validation_state = "PARTIAL"
    else:
        validation_state = "VALID"

    if dataset.status == "GEOCODING_RUNNING":
        geocode_state = "IN_PROGRESS"
    elif stop_count == 0:
        geocode_state = "NOT_STARTED"
    elif failed_count > 0:
        geocode_state = "NEEDS_ATTENTION"
    elif geocoded_count >= stop_count:
        geocode_state = "COMPLETE"
    elif geocoded_count > 0:
        geocode_state = "IN_PROGRESS"
    else:
        geocode_state = "NOT_STARTED"

    latest_plan = db.execute(select(Plan).where(Plan.dataset_id == dataset_id).order_by(Plan.created_at.desc(), Plan.id.desc()).limit(1)).scalar_one_or_none()
    latest_plan_status = latest_plan.status if latest_plan else None
    latest_plan_id = latest_plan.id if latest_plan else None
    if dataset.status == "OPTIMIZATION_RUNNING":
        optimize_state = "RUNNING"
    elif latest_plan is None:
        optimize_state = "NOT_STARTED"
    elif latest_plan.status in {"SUCCESS", "PARTIAL"}:
        optimize_state = "COMPLETE"
    elif latest_plan.status in {"CREATED", "RUNNING"}:
        optimize_state = "RUNNING"
    else:
        optimize_state = "NEEDS_ATTENTION"

    return {
        "id": dataset.id,
        "filename": dataset.filename,
        "created_at": dataset.created_at.isoformat(),
        "status": dataset.status,
        "stop_count": stop_count,
        "valid_stop_count": valid_stop_count,
        "geocode_counts": geocode_counts,
        "validation_state": validation_state,
        "geocode_state": geocode_state,
        "optimize_state": optimize_state,
        "latest_plan_id": latest_plan_id,
        "latest_plan_status": latest_plan_status,
    }


def list_stops(
    db: Session,
    dataset_id: int,
    *,
    status: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    get_dataset_or_404(db, dataset_id)

    stmt = select(Stop).where(Stop.dataset_id == dataset_id)
    if status:
        stmt = stmt.where(Stop.geocode_status == status)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stops = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()

    return {
        "items": [
            {
                "id": s.id,
                "stop_ref": s.stop_ref,
                "address": s.address,
                "postal_code": s.postal_code,
                "lat": s.lat,
                "lon": s.lon,
                "demand": s.demand,
                "service_time_min": s.service_time_min,
                "tw_start": s.tw_start,
                "tw_end": s.tw_end,
                "phone": s.phone,
                "contact_name": s.contact_name,
                "geocode_status": s.geocode_status,
                "geocode_meta": s.geocode_meta,
            }
            for s in stops
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def get_validation_error_log_csv(db: Session, dataset_id: int) -> str:
    get_dataset_or_404(db, dataset_id)

    log = db.execute(
        select(ErrorLog)
        .where(ErrorLog.dataset_id == dataset_id, ErrorLog.stage == "VALIDATION")
        .order_by(ErrorLog.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if log is None:
        raise AppError(
            message="No validation error log found",
            error_code="NOT_FOUND",
            status_code=404,
            stage="VALIDATION",
            dataset_id=dataset_id,
        )

    payload = json.loads(log.payload_json)
    csv_data = payload.get("error_log_csv")
    if not csv_data:
        invalid_rows = payload.get("invalid_rows", [])
        from app.services.validation import ValidationIssue

        issues = [ValidationIssue(row_index=row["row_index"], reason=row["reason"]) for row in invalid_rows]
        csv_data = build_error_log_csv(issues)
    return csv_data
