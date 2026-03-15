from datetime import datetime

from app.models import MLModel
from app.services.ml_ops import choose_model_version_for_prediction
from app.utils.db import SessionLocal


def test_choose_model_version_prefers_latest_model_without_rollout():
    db = SessionLocal()
    try:
        db.add_all(
            [
                MLModel(
                    version="version_old",
                    artifact_path="missing-old.pkl",
                    status="TRAINED",
                    created_at=datetime(2026, 1, 1, 10, 0, 0),
                ),
                MLModel(
                    version="version_new",
                    artifact_path="missing-new.pkl",
                    status="DEPLOYED",
                    created_at=datetime(2026, 1, 1, 11, 0, 0),
                ),
            ]
        )
        db.commit()

        assert choose_model_version_for_prediction(db) == "version_new"
    finally:
        db.close()
