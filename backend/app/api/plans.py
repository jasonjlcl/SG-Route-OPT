from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.schemas.api import PlanDetailsResponse
from app.services.export import export_driver_csv, export_plan_csv, export_plan_pdf, get_map_snapshot_svg
from app.services.optimization import get_plan_details
from app.utils.db import get_db

router = APIRouter(prefix="/api/v1/plans", tags=["plans"])


@router.get("/{plan_id}", response_model=PlanDetailsResponse)
def get_plan(plan_id: int, db: Session = Depends(get_db)) -> PlanDetailsResponse:
    return PlanDetailsResponse(**get_plan_details(db, plan_id))


@router.get("/{plan_id}/export")
def export_plan(
    plan_id: int,
    format: str = Query(pattern="^(csv|pdf)$"),
    profile: str = Query(default="driver", pattern="^(planner|driver)$"),
    vehicle_idx: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
    if format == "csv":
        csv_data = export_plan_csv(db, plan_id)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=plan_{plan_id}.csv"},
        )

    pdf_data = export_plan_pdf(db, plan_id, profile=profile, vehicle_idx=vehicle_idx)
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=plan_{plan_id}_{profile}{f'_vehicle_{vehicle_idx}' if vehicle_idx is not None else ''}.pdf"
        },
    )


@router.get("/{plan_id}/export/driver-csv")
def export_driver_plan_csv(plan_id: int, db: Session = Depends(get_db)) -> Response:
    csv_data = export_driver_csv(db, plan_id)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=plan_{plan_id}_driver.csv"},
    )


@router.get("/{plan_id}/map-snapshot")
def export_map_snapshot(
    plan_id: int,
    vehicle_idx: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
    svg = get_map_snapshot_svg(db, plan_id, vehicle_idx=vehicle_idx)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Content-Disposition": f"inline; filename=plan_{plan_id}_map.svg"},
    )
