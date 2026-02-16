from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MLModel, PredictionCache, PredictionLog
from app.services.cache import get_cache
from app.services.ml_ops import choose_model_version_for_prediction

ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "ml" / "artifacts"


@dataclass
class PredictionResult:
    duration_s: float
    model_version: str


class MLPredictionEngine:
    def __init__(self) -> None:
        self.cache = get_cache()
        self._model_cache: dict[str, Any] = {}

    def _load_model(self, db: Session, version: str) -> Any | None:
        if version in self._model_cache:
            return self._model_cache[version]

        model_row = db.execute(select(MLModel).where(MLModel.version == version)).scalar_one_or_none()
        if model_row is None:
            return None

        model_path = Path(model_row.artifact_path)
        if not model_path.exists():
            model_path = ARTIFACT_DIR / f"model_{version}.joblib"
            if not model_path.exists():
                return None

        model = joblib.load(model_path)
        self._model_cache[version] = model
        return model

    def _key(self, od_cache_id: int, model_version: str) -> str:
        return f"pred:{od_cache_id}:{model_version}"

    def predict_duration(
        self,
        db: Session,
        *,
        od_cache_id: int,
        base_duration_s: float,
        distance_m: float,
        depart_dt: datetime,
        origin_lat: float | None = None,
        origin_lon: float | None = None,
        dest_lat: float | None = None,
        dest_lon: float | None = None,
    ) -> PredictionResult:
        selected_version = choose_model_version_for_prediction(db)
        model_version = selected_version or "fallback_v1"

        if od_cache_id > 0:
            key = self._key(od_cache_id, model_version)
            redis_hit = self.cache.get(key)
            if redis_hit:
                duration = float(redis_hit["duration_s"])
                self._log_prediction(
                    db,
                    model_version=model_version,
                    origin_lat=origin_lat,
                    origin_lon=origin_lon,
                    dest_lat=dest_lat,
                    dest_lon=dest_lon,
                    base_duration_s=base_duration_s,
                    predicted_duration_s=duration,
                    distance_m=distance_m,
                    depart_dt=depart_dt,
                    source="redis_cache",
                )
                return PredictionResult(duration_s=duration, model_version=model_version)

            cached = db.execute(
                select(PredictionCache).where(
                    PredictionCache.od_cache_id == od_cache_id,
                    PredictionCache.model_version == model_version,
                )
            ).scalar_one_or_none()
            if cached:
                duration = float(cached.predicted_duration_s)
                self.cache.set(key, {"duration_s": duration}, ttl_seconds=24 * 3600)
                self._log_prediction(
                    db,
                    model_version=model_version,
                    origin_lat=origin_lat,
                    origin_lon=origin_lon,
                    dest_lat=dest_lat,
                    dest_lon=dest_lon,
                    base_duration_s=base_duration_s,
                    predicted_duration_s=duration,
                    distance_m=distance_m,
                    depart_dt=depart_dt,
                    source="db_cache",
                )
                return PredictionResult(duration_s=duration, model_version=model_version)

        hour = depart_dt.hour
        day_of_week = depart_dt.weekday()
        model = self._load_model(db, model_version) if selected_version else None

        if model is None:
            duration = self._fallback_duration(base_duration_s, hour)
            model_version = "fallback_v1"
        else:
            features = np.array([[base_duration_s, distance_m, hour, day_of_week]], dtype=float)
            predicted = float(model.predict(features)[0])
            duration = max(1.0, predicted)

        if od_cache_id > 0:
            row = PredictionCache(
                od_cache_id=od_cache_id,
                model_version=model_version,
                predicted_duration_s=duration,
            )
            db.add(row)
            db.commit()
            self.cache.set(self._key(od_cache_id, model_version), {"duration_s": duration}, ttl_seconds=24 * 3600)

        self._log_prediction(
            db,
            model_version=model_version,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            dest_lat=dest_lat,
            dest_lon=dest_lon,
            base_duration_s=base_duration_s,
            predicted_duration_s=duration,
            distance_m=distance_m,
            depart_dt=depart_dt,
            source="inference",
        )

        return PredictionResult(duration_s=duration, model_version=model_version)

    def _log_prediction(
        self,
        db: Session,
        *,
        model_version: str,
        origin_lat: float | None,
        origin_lon: float | None,
        dest_lat: float | None,
        dest_lon: float | None,
        base_duration_s: float,
        predicted_duration_s: float,
        distance_m: float,
        depart_dt: datetime,
        source: str,
    ) -> None:
        if None in {origin_lat, origin_lon, dest_lat, dest_lon}:
            return

        row = PredictionLog(
            model_version=model_version,
            origin_lat=float(origin_lat),
            origin_lon=float(origin_lon),
            dest_lat=float(dest_lat),
            dest_lon=float(dest_lon),
            features_json=json.dumps(
                {
                    "base_duration_s": base_duration_s,
                    "distance_m": distance_m,
                    "hour": depart_dt.hour,
                    "day_of_week": depart_dt.weekday(),
                }
            ),
            predicted_duration_s=float(predicted_duration_s),
            base_duration_s=float(base_duration_s),
            request_context_json=json.dumps(
                {
                    "hour": depart_dt.hour,
                    "day_of_week": depart_dt.weekday(),
                    "depart_bucket": depart_dt.strftime("%H:%M"),
                    "source": source,
                }
            ),
        )
        db.add(row)
        db.commit()

    @staticmethod
    def _fallback_duration(base_duration_s: float, hour: int) -> float:
        if 7 <= hour <= 9:
            peak_factor = 0.25
        elif 17 <= hour <= 20:
            peak_factor = 0.28
        elif 10 <= hour <= 16:
            peak_factor = 0.12
        else:
            peak_factor = 0.05
        return max(1.0, base_duration_s * (1 + peak_factor))


_engine: MLPredictionEngine | None = None


def get_ml_engine() -> MLPredictionEngine:
    global _engine
    if _engine is None:
        _engine = MLPredictionEngine()
    return _engine
