import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.models import PredictionLog
from app.services.ml_engine import get_ml_engine
from app.services.ml_ops import list_models, set_rollout, train_and_register_model
from app.utils.db import SessionLocal


def test_ml_registry_train_rollout_predict_log():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "history.csv"
        rows = []
        for hour in range(8, 18):
            rows.append(
                {
                    "origin_lat": 1.30,
                    "origin_lon": 103.80,
                    "dest_lat": 1.34,
                    "dest_lon": 103.86,
                    "base_duration_s": 900 + hour * 2,
                    "distance_m": 4200,
                    "timestamp": f"2025-01-10T{hour:02d}:00:00",
                    "actual_duration_s": 1000 + hour * 3,
                }
            )
        pd.DataFrame(rows).to_csv(csv_path, index=False)

        db = SessionLocal()
        try:
            train_result = train_and_register_model(db, dataset_path=str(csv_path))
            assert train_result["model_version"].startswith("v")

            models = list_models(db)
            assert any(model["version"] == train_result["model_version"] for model in models)
            set_rollout(db, active_version=train_result["model_version"], enabled=False)

            engine = get_ml_engine()
            pred = engine.predict_duration(
                db,
                od_cache_id=-1,
                base_duration_s=1000,
                distance_m=4500,
                depart_dt=datetime.fromisoformat("2025-01-11T09:00:00"),
                origin_lat=1.30,
                origin_lon=103.80,
                dest_lat=1.34,
                dest_lon=103.86,
            )
            assert pred.duration_s > 0
            assert pred.model_version in {train_result["model_version"], "fallback_v1"}

            logs = db.query(PredictionLog).all()
            assert len(logs) >= 1
        finally:
            db.close()

