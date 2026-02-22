from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Dataset, Stop
from app.utils.errors import AppError
from app.utils.settings import get_settings


def validate_optimize_request_scale(db: Session, *, dataset_id: int) -> dict[str, int]:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError(
            message=f"Dataset {dataset_id} not found",
            error_code="NOT_FOUND",
            status_code=404,
        )

    stop_count = int(db.execute(select(func.count(Stop.id)).where(Stop.dataset_id == dataset_id)).scalar_one() or 0)
    node_count = stop_count + 1
    estimated_matrix_elements = max(0, node_count * node_count - node_count)

    settings = get_settings()
    max_stops = int(settings.optimize_max_stops)
    max_matrix_elements = int(settings.optimize_max_matrix_elements)

    if stop_count > max_stops:
        raise AppError(
            message="Optimize request exceeds stop limit; split the dataset or reduce stops.",
            error_code="OPTIMIZE_MAX_STOPS_EXCEEDED",
            status_code=400,
            stage="OPTIMIZATION",
            dataset_id=dataset_id,
            details={
                "dataset_id": dataset_id,
                "stop_count": stop_count,
                "max_stops": max_stops,
                "estimated_matrix_elements": estimated_matrix_elements,
                "max_matrix_elements": max_matrix_elements,
            },
        )

    if estimated_matrix_elements > max_matrix_elements:
        raise AppError(
            message="Optimize request exceeds matrix size limit; split the dataset into smaller batches.",
            error_code="OPTIMIZE_MAX_MATRIX_ELEMENTS_EXCEEDED",
            status_code=400,
            stage="OPTIMIZATION",
            dataset_id=dataset_id,
            details={
                "dataset_id": dataset_id,
                "stop_count": stop_count,
                "max_stops": max_stops,
                "estimated_matrix_elements": estimated_matrix_elements,
                "max_matrix_elements": max_matrix_elements,
            },
        )

    return {
        "stop_count": stop_count,
        "node_count": node_count,
        "estimated_matrix_elements": estimated_matrix_elements,
    }
