from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas.api import ManualGeocodeRequest
from app.services.geocoding import manual_resolve_stop
from app.utils.db import get_db

router = APIRouter(prefix="/api/v1/stops", tags=["stops"])


@router.post("/{stop_id}/geocode/manual")
def manual_geocode(stop_id: int, payload: ManualGeocodeRequest, db: Session = Depends(get_db)) -> dict:
    return manual_resolve_stop(
        db,
        stop_id,
        corrected_address=payload.corrected_address,
        corrected_postal_code=payload.corrected_postal_code,
        lat=payload.lat,
        lon=payload.lon,
    )
