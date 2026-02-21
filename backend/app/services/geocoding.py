from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dataset, Stop
from app.services.onemap_client import get_onemap_client
from app.utils.errors import AppError, log_error

NULL_LIKE_TEXT = {"nan", "none", "null", "<na>"}


def _normalize_wgs84(lat_value: Any, lon_value: Any) -> tuple[float, float]:
    try:
        lat = float(lat_value)
        lon = float(lon_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Coordinate values must be numeric") from exc

    swapped = abs(lat) > 90 and abs(lon) <= 90 and abs(lat) <= 180
    if swapped:
        lat, lon = lon, lat

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Coordinate must be WGS84 latitude/longitude")

    # Defensive guard against projected coordinate systems (for example SVY21 easting/northing).
    if abs(lat) > 1000 or abs(lon) > 1000:
        raise ValueError("Projected coordinates are not supported; use WGS84 decimal latitude/longitude")

    return lat, lon


def _clean_query_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in NULL_LIKE_TEXT:
        return None
    return text


def geocode_dataset(
    db: Session,
    dataset_id: int,
    *,
    failed_only: bool = False,
    force_all: bool = False,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError(message=f"Dataset {dataset_id} not found", error_code="NOT_FOUND", status_code=404)

    if force_all:
        stops = db.execute(select(Stop).where(Stop.dataset_id == dataset_id)).scalars().all()
    else:
        statuses = ["FAILED"] if failed_only else ["PENDING", "FAILED"]
        stops = db.execute(select(Stop).where(Stop.dataset_id == dataset_id, Stop.geocode_status.in_(statuses))).scalars().all()

    client = get_onemap_client()
    failed: list[dict[str, Any]] = []
    success_count = 0
    total = len(stops)

    if progress_cb:
        progress_cb(5, f"Geocoding 0/{total} stops")

    for idx, stop in enumerate(stops, start=1):
        # Prefer postal code when present because it is less ambiguous than free-text address.
        query = _clean_query_text(stop.postal_code) or _clean_query_text(stop.address)
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
            lat, lon = _normalize_wgs84(first.get("LATITUDE"), first.get("LONGITUDE"))
            stop.lat = lat
            stop.lon = lon
            resolved_address = _clean_query_text(first.get("ADDRESS"))
            resolved_postal = _clean_query_text(first.get("POSTAL"))
            if resolved_address:
                stop.address = resolved_address
            if resolved_postal:
                stop.postal_code = resolved_postal
            stop.geocode_status = "SUCCESS"
            source = "mock" if str(first.get("MOCK", "")).lower() == "true" else "onemap"
            stop.geocode_meta = json.dumps({"source": source, "query": query})
            success_count += 1
        except Exception as exc:  # noqa: BLE001
            stop.geocode_status = "FAILED"
            stop.geocode_meta = json.dumps({"error": str(exc), "query": query})
            failed.append({"stop_id": stop.id, "stop_ref": stop.stop_ref, "reason": str(exc)})
            log_error(db, "GEOCODING", str(exc), dataset_id=dataset_id, details={"stop_id": stop.id})
        if progress_cb and total > 0:
            progress = min(95, int((idx / total) * 100))
            progress_cb(progress, f"Geocoding {idx}/{total} stops")

    if failed and success_count == 0:
        dataset.status = "GEOCODING_FAILED"
    elif failed:
        dataset.status = "GEOCODING_PARTIAL"
    else:
        dataset.status = "GEOCODED"

    db.commit()
    if progress_cb:
        progress_cb(100, f"Geocoding complete: {success_count}/{total} resolved")

    return {
        "dataset_id": dataset_id,
        "failed_only": failed_only,
        "force_all": force_all,
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
        normalized_lat, normalized_lon = _normalize_wgs84(lat, lon)
        resolved_address = _clean_query_text(corrected_address)
        resolved_postal = _clean_query_text(corrected_postal_code)
        reverse_source: str | None = None

        if resolved_address is None or resolved_postal is None:
            try:
                reverse = get_onemap_client().reverse_geocode(normalized_lat, normalized_lon)
                reverse_source = str(reverse.get("source") or "")
                if resolved_address is None:
                    resolved_address = _clean_query_text(reverse.get("address"))
                if resolved_postal is None:
                    resolved_postal = _clean_query_text(reverse.get("postal_code"))
            except Exception as exc:  # noqa: BLE001
                log_error(
                    db,
                    "GEOCODING",
                    str(exc),
                    dataset_id=stop.dataset_id,
                    details={"stop_id": stop.id, "op": "reverse_geocode", "lat": normalized_lat, "lon": normalized_lon},
                )

        stop.lat = normalized_lat
        stop.lon = normalized_lon
        if resolved_address:
            stop.address = resolved_address
        if resolved_postal:
            stop.postal_code = resolved_postal
        stop.geocode_status = "MANUAL"
        stop.geocode_meta = json.dumps({"source": "manual_pin", "reverse_source": reverse_source})
        db.commit()
        return {
            "stop_id": stop.id,
            "status": stop.geocode_status,
            "lat": stop.lat,
            "lon": stop.lon,
            "address": stop.address,
            "postal_code": stop.postal_code,
        }

    query = _clean_query_text(corrected_address) or _clean_query_text(corrected_postal_code)
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
    lat, lon = _normalize_wgs84(first.get("LATITUDE"), first.get("LONGITUDE"))
    stop.lat = lat
    stop.lon = lon
    stop.address = _clean_query_text(first.get("ADDRESS")) or stop.address
    stop.postal_code = _clean_query_text(first.get("POSTAL")) or stop.postal_code
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
