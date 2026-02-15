from __future__ import annotations

import glob
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PredictionCache
from app.services.cache import get_cache

ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "ml" / "artifacts"


@dataclass
class PredictionResult:
    duration_s: float
    model_version: str


class MLPredictionEngine:
    def __init__(self) -> None:
        self.cache = get_cache()
        self._model = None
        self._metadata: dict[str, str] | None = None
        self._load_latest_model()

    def _load_latest_model(self) -> None:
        model_files = sorted(glob.glob(str(ARTIFACT_DIR / "model_*.joblib")))
        if not model_files:
            self._model = None
            self._metadata = {"model_version": "fallback_v1"}
            return

        latest = model_files[-1]
        metadata_file = latest.replace(".joblib", ".meta.json")
        self._model = joblib.load(latest)
        if Path(metadata_file).exists():
            self._metadata = json.loads(Path(metadata_file).read_text(encoding="utf-8"))
        else:
            self._metadata = {"model_version": Path(latest).stem}

    @property
    def model_version(self) -> str:
        if not self._metadata:
            return "fallback_v1"
        return self._metadata.get("model_version", "fallback_v1")

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
    ) -> PredictionResult:
        model_version = self.model_version

        if od_cache_id > 0:
            key = self._key(od_cache_id, model_version)
            redis_hit = self.cache.get(key)
            if redis_hit:
                return PredictionResult(duration_s=float(redis_hit["duration_s"]), model_version=model_version)

            cached = db.execute(
                select(PredictionCache).where(
                    PredictionCache.od_cache_id == od_cache_id,
                    PredictionCache.model_version == model_version,
                )
            ).scalar_one_or_none()
            if cached:
                self.cache.set(key, {"duration_s": cached.predicted_duration_s}, ttl_seconds=24 * 3600)
                return PredictionResult(duration_s=float(cached.predicted_duration_s), model_version=model_version)

        hour = depart_dt.hour
        day_of_week = depart_dt.weekday()

        if self._model is None:
            duration = self._fallback_duration(base_duration_s, hour)
        else:
            features = np.array([[base_duration_s, distance_m, hour, day_of_week]], dtype=float)
            predicted = float(self._model.predict(features)[0])
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

        return PredictionResult(duration_s=duration, model_version=model_version)

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
