from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dataset, Stop
from app.services.onemap_client import get_onemap_client
from app.utils.errors import AppError, log_error


def geocode_dataset(db: Session, dataset_id: int, *, failed_only: bool = False) -> dict[str, Any]:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError(message=f"Dataset {dataset_id} not found", error_code="NOT_FOUND", status_code=404)

    statuses = ["FAILED"] if failed_only else ["PENDING", "FAILED"]
    stops = db.execute(select(Stop).where(Stop.dataset_id == dataset_id, Stop.geocode_status.in_(statuses))).scalars().all()

    client = get_onemap_client()
    failed: list[dict[str, Any]] = []
    success_count = 0

    for stop in stops:
        query = stop.address or stop.postal_code
        if not query:
            stop.geocode_status = "FAILED"
            stop.geocode_meta = json.dumps({"error": "Missing address and postal_code"})
            failed.append({"stop_id": stop.id, "stop_ref": stop.stop_ref, "reason": "missing query"})
            continue

        try:
            data = client.search(query)
            results = data.get("results", [])
            if not results:
                stop.geocode_status = "FAILED"
                stop.geocode_meta = json.dumps({"error": "No geocode result"})
                failed.append({"stop_id": stop.id, "stop_ref": stop.stop_ref, "reason": "no result"})
                continue

            first = results[0]
            stop.lat = float(first.get("LATITUDE"))
            stop.lon = float(first.get("LONGITUDE"))
            if first.get("ADDRESS"):
                stop.address = first.get("ADDRESS")
            if first.get("POSTAL"):
                stop.postal_code = first.get("POSTAL")
            stop.geocode_status = "SUCCESS"
            stop.geocode_meta = json.dumps({"source": "onemap", "query": query})
            success_count += 1
        except Exception as exc:  # noqa: BLE001
            stop.geocode_status = "FAILED"
            stop.geocode_meta = json.dumps({"error": str(exc), "query": query})
            failed.append({"stop_id": stop.id, "stop_ref": stop.stop_ref, "reason": str(exc)})
            log_error(db, "GEOCODING", str(exc), dataset_id=dataset_id, details={"stop_id": stop.id})

    if failed and success_count == 0:
        dataset.status = "GEOCODING_FAILED"
    elif failed:
        dataset.status = "GEOCODING_PARTIAL"
    else:
        dataset.status = "GEOCODED"

    db.commit()

    return {
        "dataset_id": dataset_id,
        "failed_only": failed_only,
        "total_attempted": len(stops),
        "success_count": success_count,
        "failed_count": len(failed),
        "failed_stops": failed,
        "status": dataset.status,
    }


def manual_resolve_stop(
    db: Session,
    stop_id: int,
    *,
    corrected_address: str | None,
    corrected_postal_code: str | None,
    lat: float | None,
    lon: float | None,
) -> dict[str, Any]:
    stop = db.get(Stop, stop_id)
    if stop is None:
        raise AppError(message=f"Stop {stop_id} not found", error_code="NOT_FOUND", status_code=404)

    if lat is not None and lon is not None:
        stop.lat = lat
        stop.lon = lon
        if corrected_address:
            stop.address = corrected_address
        if corrected_postal_code:
            stop.postal_code = corrected_postal_code
        stop.geocode_status = "MANUAL"
        stop.geocode_meta = json.dumps({"source": "manual_pin"})
        db.commit()
        return {"stop_id": stop.id, "status": stop.geocode_status, "lat": stop.lat, "lon": stop.lon}

    query = corrected_address or corrected_postal_code
    if not query:
        raise AppError(
            message="Provide corrected_address/corrected_postal_code or lat/lon",
            error_code="VALIDATION_ERROR",
            status_code=400,
            stage="GEOCODING",
        )

    client = get_onemap_client()
    data = client.search(query)
    results = data.get("results", [])
    if not results:
        raise AppError(
            message="No geocode result for corrected query",
            error_code="GEOCODE_NOT_FOUND",
            status_code=404,
            stage="GEOCODING",
            details={"query": query},
        )

    first = results[0]
    stop.lat = float(first.get("LATITUDE"))
    stop.lon = float(first.get("LONGITUDE"))
    stop.address = first.get("ADDRESS") or stop.address
    stop.postal_code = first.get("POSTAL") or stop.postal_code
    stop.geocode_status = "MANUAL"
    stop.geocode_meta = json.dumps({"source": "manual_search", "query": query})
    db.commit()

    return {
        "stop_id": stop.id,
        "status": stop.geocode_status,
        "lat": stop.lat,
        "lon": stop.lon,
        "address": stop.address,
        "postal_code": stop.postal_code,
    }
