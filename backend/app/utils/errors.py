from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import ErrorLog


@dataclass
class AppError(Exception):
    message: str
    error_code: str = "APP_ERROR"
    status_code: int = 400
    details: Any = None
    stage: str = "API"
    dataset_id: int | None = None

    def __str__(self) -> str:
        return self.message


def log_error(
    db: Session,
    stage: str,
    message: str,
    dataset_id: int | None = None,
    details: Any = None,
) -> None:
    payload = {
        "message": message,
        "details": details,
        "timestamp": datetime.utcnow().isoformat(),
    }
    db.add(
        ErrorLog(
            dataset_id=dataset_id,
            stage=stage,
            payload_json=json.dumps(payload, default=str),
        )
    )
    db.commit()
