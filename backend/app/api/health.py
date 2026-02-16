from fastapi import APIRouter

from app.services.ml_ops import latest_monitoring_snapshot
from app.utils.db import SessionLocal
from app.utils.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    monitoring = {}
    db = SessionLocal()
    try:
        monitoring = latest_monitoring_snapshot(db)
    except Exception:
        monitoring = {}
    finally:
        db.close()
    return {
        "status": "ok",
        "env": settings.app_env,
        "ml_needs_retrain": bool(monitoring.get("needs_retrain", False)),
    }
