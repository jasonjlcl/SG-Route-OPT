from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MLModel, PredictionCache, PredictionLog
from app.services.cache import get_cache
from app.services.ml_features import build_feature_dict, fallback_duration, feature_vector
from app.services.ml_ops import choose_model_version_for_prediction
from app.services.storage import download_bytes

ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "ml" / "artifacts"
PredictionStrategy = Literal["auto", "model", "fallback"]
LOGGER = logging.getLogger(__name__)


@dataclass
class PredictionResult:
    duration_s: float
    model_version: str
    lower_s: float
    upper_s: float
    std_s: float
    strategy: PredictionStrategy


class MLPredictionEngine:
    def __init__(self) -> None:
        self.cache = get_cache()
        self._model_cache: dict[str, Any] = {}
        self._metrics_cache: dict[str, dict[str, Any]] = {}

    def _load_model_row(self, db: Session, version: str) -> MLModel | None:
        return db.execute(select(MLModel).where(MLModel.version == version)).scalar_one_or_none()

    @staticmethod
    def _object_path_from_gcs_uri(gcs_uri: str | None) -> str | None:
        text = str(gcs_uri or "").strip()
        if not text.startswith("gs://"):
            return None
        no_scheme = text[5:]
        if "/" not in no_scheme:
            return None
        _, object_path = no_scheme.split("/", 1)
        clean = object_path.strip("/")
        return clean or None

    def _load_model(self, db: Session, version: str) -> Any | None:
        if version in self._model_cache:
            return self._model_cache[version]

        model_row = self._load_model_row(db, version)
        if model_row is None:
            return None

        candidate_paths: list[Path] = []
        artifact_path = str(model_row.artifact_path or "").strip()
        if artifact_path:
            candidate_paths.append(Path(artifact_path))
        candidate_paths.append(ARTIFACT_DIR / f"model_{version}.joblib")
        candidate_paths.append(ARTIFACT_DIR / version / "model.pkl")

        for path in candidate_paths:
            if not path.exists():
                continue
            try:
                model = joblib.load(path)
                self._model_cache[version] = model
                return model
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Failed to load local ML model artifact for version=%s path=%s: %s", version, path, exc)

        object_path = self._object_path_from_gcs_uri(model_row.artifact_gcs_uri)
        if object_path:
            try:
                payload = download_bytes(object_path=object_path)
                if payload:
                    model = joblib.load(BytesIO(payload))
                    self._model_cache[version] = model
                    return model
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "Failed to load ML model artifact from GCS for version=%s object_path=%s: %s",
                    version,
                    object_path,
                    exc,
                )

        return None

    def _metrics_for_version(self, db: Session, version: str) -> dict[str, Any]:
        if version in self._metrics_cache:
            return self._metrics_cache[version]
        row = self._load_model_row(db, version)
        metrics: dict[str, Any] = {}
        if row and row.metrics_json:
            try:
                decoded = json.loads(row.metrics_json)
                if isinstance(decoded, dict):
                    metrics = decoded
            except json.JSONDecodeError:
                metrics = {}
        self._metrics_cache[version] = metrics
        return metrics

    def _uncertainty(self, db: Session, model_version: str, duration_s: float) -> tuple[float, float, float]:
        if model_version == "fallback_v1":
            # fallback has wider uncertainty
            std_s = max(20.0, duration_s * 0.18)
            p90 = max(30.0, duration_s * 0.28)
            return std_s, p90, max(15.0, duration_s * 0.12)

        metrics = self._metrics_for_version(db, model_version)
        std_s = float(metrics.get("residual_std_s") or metrics.get("std_s") or max(15.0, duration_s * 0.08))
        p90 = float(metrics.get("uncertainty_p90_s") or metrics.get("p90_abs_error_s") or max(25.0, duration_s * 0.12))
        p50 = float(metrics.get("uncertainty_p50_s") or metrics.get("p50_abs_error_s") or max(10.0, duration_s * 0.06))
        return std_s, p90, p50

    def _key(self, od_cache_id: int, model_version: str) -> str:
        return f"pred:{od_cache_id}:{model_version}"

    def _resolve_model_version(self, db: Session, *, strategy: PredictionStrategy, force_model_version: str | None) -> str | None:
        if strategy == "fallback":
            return None
        if force_model_version:
            return force_model_version
        return choose_model_version_for_prediction(db)

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
        strategy: PredictionStrategy = "auto",
        force_model_version: str | None = None,
        log_prediction: bool = True,
    ) -> PredictionResult:
        selected_version = self._resolve_model_version(db, strategy=strategy, force_model_version=force_model_version)
        model_version = selected_version or "fallback_v1"

        if od_cache_id > 0:
            key = self._key(od_cache_id, model_version)
            redis_hit = self.cache.get(key)
            if redis_hit:
                duration = float(redis_hit["duration_s"])
                std_s, p90, _ = self._uncertainty(db, model_version, duration)
                lower = max(1.0, duration - p90)
                upper = duration + p90
                if log_prediction:
                    self._log_prediction(
                        db,
                        model_version=model_version,
                        origin_lat=origin_lat,
                        origin_lon=origin_lon,
                        dest_lat=dest_lat,
                        dest_lon=dest_lon,
                        feature_payload={
                            "base_duration_s": float(base_duration_s),
                            "distance_m": float(distance_m),
                            "hour": depart_dt.hour,
                            "day_of_week": depart_dt.weekday(),
                        },
                        predicted_duration_s=duration,
                        base_duration_s=base_duration_s,
                        depart_dt=depart_dt,
                        source="redis_cache",
                        strategy=strategy,
                        uncertainty={"lower_s": lower, "upper_s": upper, "std_s": std_s},
                    )
                return PredictionResult(
                    duration_s=duration,
                    model_version=model_version,
                    lower_s=lower,
                    upper_s=upper,
                    std_s=std_s,
                    strategy=strategy,
                )

            cached = db.execute(
                select(PredictionCache).where(
                    PredictionCache.od_cache_id == od_cache_id,
                    PredictionCache.model_version == model_version,
                )
            ).scalar_one_or_none()
            if cached:
                duration = float(cached.predicted_duration_s)
                self.cache.set(key, {"duration_s": duration}, ttl_seconds=24 * 3600)
                std_s, p90, _ = self._uncertainty(db, model_version, duration)
                lower = max(1.0, duration - p90)
                upper = duration + p90
                if log_prediction:
                    self._log_prediction(
                        db,
                        model_version=model_version,
                        origin_lat=origin_lat,
                        origin_lon=origin_lon,
                        dest_lat=dest_lat,
                        dest_lon=dest_lon,
                        feature_payload={
                            "base_duration_s": float(base_duration_s),
                            "distance_m": float(distance_m),
                            "hour": depart_dt.hour,
                            "day_of_week": depart_dt.weekday(),
                        },
                        predicted_duration_s=duration,
                        base_duration_s=base_duration_s,
                        depart_dt=depart_dt,
                        source="db_cache",
                        strategy=strategy,
                        uncertainty={"lower_s": lower, "upper_s": upper, "std_s": std_s},
                    )
                return PredictionResult(
                    duration_s=duration,
                    model_version=model_version,
                    lower_s=lower,
                    upper_s=upper,
                    std_s=std_s,
                    strategy=strategy,
                )

        # If coordinates are missing, fallback to simple features.
        if None in {origin_lat, origin_lon, dest_lat, dest_lon}:
            duration = fallback_duration(base_duration_s, depart_dt.hour)
            model_version = "fallback_v1"
            std_s, p90, _ = self._uncertainty(db, model_version, duration)
            lower = max(1.0, duration - p90)
            upper = duration + p90
            if log_prediction:
                self._log_prediction(
                    db,
                    model_version=model_version,
                    origin_lat=origin_lat,
                    origin_lon=origin_lon,
                    dest_lat=dest_lat,
                    dest_lon=dest_lon,
                    feature_payload={
                        "base_duration_s": float(base_duration_s),
                        "distance_m": float(distance_m),
                        "hour": depart_dt.hour,
                        "day_of_week": depart_dt.weekday(),
                    },
                    predicted_duration_s=duration,
                    base_duration_s=base_duration_s,
                    depart_dt=depart_dt,
                    source="inference_missing_coords",
                    strategy=strategy,
                    uncertainty={"lower_s": lower, "upper_s": upper, "std_s": std_s},
                )
            return PredictionResult(
                duration_s=duration,
                model_version=model_version,
                lower_s=lower,
                upper_s=upper,
                std_s=std_s,
                strategy=strategy,
            )

        feature_payload = build_feature_dict(
            base_duration_s=float(base_duration_s),
            distance_m=float(distance_m),
            depart_dt=depart_dt,
            origin_lat=float(origin_lat),
            origin_lon=float(origin_lon),
            dest_lat=float(dest_lat),
            dest_lon=float(dest_lon),
        )

        model = self._load_model(db, model_version) if selected_version is not None else None
        if strategy == "fallback" or model is None:
            duration = fallback_duration(base_duration_s, depart_dt.hour)
            model_version = "fallback_v1"
        else:
            features = np.array([feature_vector(feature_payload)], dtype=float)
            predicted = float(model.predict(features)[0])
            duration = max(1.0, predicted)

        std_s, p90, _ = self._uncertainty(db, model_version, duration)
        lower = max(1.0, duration - p90)
        upper = duration + p90

        if od_cache_id > 0:
            row = PredictionCache(
                od_cache_id=od_cache_id,
                model_version=model_version,
                predicted_duration_s=duration,
            )
            db.add(row)
            db.commit()
            self.cache.set(self._key(od_cache_id, model_version), {"duration_s": duration}, ttl_seconds=24 * 3600)

        if log_prediction:
            self._log_prediction(
                db,
                model_version=model_version,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                dest_lat=dest_lat,
                dest_lon=dest_lon,
                feature_payload=feature_payload,
                predicted_duration_s=duration,
                base_duration_s=base_duration_s,
                depart_dt=depart_dt,
                source="inference",
                strategy=strategy,
                uncertainty={"lower_s": lower, "upper_s": upper, "std_s": std_s},
            )

        return PredictionResult(
            duration_s=duration,
            model_version=model_version,
            lower_s=lower,
            upper_s=upper,
            std_s=std_s,
            strategy=strategy,
        )

    def _log_prediction(
        self,
        db: Session,
        *,
        model_version: str,
        origin_lat: float | None,
        origin_lon: float | None,
        dest_lat: float | None,
        dest_lon: float | None,
        feature_payload: dict[str, Any],
        predicted_duration_s: float,
        base_duration_s: float,
        depart_dt: datetime,
        source: str,
        strategy: PredictionStrategy,
        uncertainty: dict[str, float],
    ) -> None:
        if None in {origin_lat, origin_lon, dest_lat, dest_lon}:
            return

        row = PredictionLog(
            model_version=model_version,
            origin_lat=float(origin_lat),
            origin_lon=float(origin_lon),
            dest_lat=float(dest_lat),
            dest_lon=float(dest_lon),
            features_json=json.dumps(feature_payload),
            predicted_duration_s=float(predicted_duration_s),
            base_duration_s=float(base_duration_s),
            request_context_json=json.dumps(
                {
                    "hour": depart_dt.hour,
                    "day_of_week": depart_dt.weekday(),
                    "depart_bucket": depart_dt.strftime("%H:%M"),
                    "source": source,
                    "strategy": strategy,
                    **uncertainty,
                }
            ),
        )
        db.add(row)
        db.commit()


_engine: MLPredictionEngine | None = None


def get_ml_engine() -> MLPredictionEngine:
    global _engine
    if _engine is None:
        _engine = MLPredictionEngine()
    return _engine
