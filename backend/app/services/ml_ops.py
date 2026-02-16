from __future__ import annotations

import json
import random
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import joblib
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error
from sklearn.model_selection import train_test_split
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ActualTravelTime, MLModel, MLMonitoring, ModelRollout, PredictionLog
from app.utils.settings import get_settings

ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "ml" / "artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    radius = 6371000.0
    p = math.pi / 180
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def list_models(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(select(MLModel).order_by(MLModel.created_at.desc(), MLModel.id.desc())).scalars().all()
    return [
        {
            "id": row.id,
            "version": row.version,
            "created_at": row.created_at.isoformat(),
            "artifact_path": row.artifact_path,
            "feature_schema_json": json.loads(row.feature_schema_json) if row.feature_schema_json else None,
            "training_data_ref": row.training_data_ref,
            "metrics_json": json.loads(row.metrics_json) if row.metrics_json else None,
            "status": row.status,
        }
        for row in rows
    ]


def get_latest_rollout(db: Session) -> dict[str, Any] | None:
    rollout = db.execute(select(ModelRollout).order_by(ModelRollout.created_at.desc(), ModelRollout.id.desc()).limit(1)).scalar_one_or_none()
    if rollout is None:
        return None
    return {
        "id": rollout.id,
        "created_at": rollout.created_at.isoformat(),
        "active_version": rollout.active_version,
        "canary_version": rollout.canary_version,
        "canary_percent": rollout.canary_percent,
        "enabled": rollout.enabled,
    }


def set_rollout(
    db: Session,
    *,
    active_version: str,
    canary_version: str | None = None,
    canary_percent: int = 0,
    enabled: bool = False,
) -> dict[str, Any]:
    rollout = ModelRollout(
        active_version=active_version,
        canary_version=canary_version,
        canary_percent=max(0, min(100, int(canary_percent))),
        enabled=enabled,
    )
    db.add(rollout)
    db.commit()
    db.refresh(rollout)

    active_row = db.execute(select(MLModel).where(MLModel.version == active_version)).scalar_one_or_none()
    if active_row:
        active_row.status = "DEPLOYED"
    if canary_version:
        canary_row = db.execute(select(MLModel).where(MLModel.version == canary_version)).scalar_one_or_none()
        if canary_row and canary_row.status != "DEPLOYED":
            canary_row.status = "TRAINED"
    db.commit()

    return get_latest_rollout(db) or {}


def _build_training_frame_from_actuals(db: Session) -> pd.DataFrame:
    rows = db.execute(select(ActualTravelTime)).scalars().all()
    if not rows:
        raise ValueError("No actual travel times available for retraining")

    records: list[dict[str, Any]] = []
    for row in rows:
        timestamp = datetime.fromisoformat(row.timestamp_iso)
        distance = _haversine_m(row.origin_lat, row.origin_lon, row.dest_lat, row.dest_lon)
        base_duration = max(30.0, distance / 9.0)
        records.append(
            {
                "origin_lat": row.origin_lat,
                "origin_lon": row.origin_lon,
                "dest_lat": row.dest_lat,
                "dest_lon": row.dest_lon,
                "base_duration_s": base_duration,
                "distance_m": distance,
                "timestamp": timestamp.isoformat(),
                "actual_duration_s": row.actual_duration_s,
            }
        )
    return pd.DataFrame(records)


def train_and_register_model(
    db: Session,
    *,
    dataset_path: str | None,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    if progress_cb:
        progress_cb(10, "Loading training dataset")

    if dataset_path:
        df = pd.read_csv(dataset_path)
        training_data_ref = dataset_path
    else:
        df = _build_training_frame_from_actuals(db)
        training_data_ref = "actual_travel_times"

    required_cols = {"origin_lat", "origin_lon", "dest_lat", "dest_lon", "base_duration_s", "timestamp", "actual_duration_s"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    if "distance_m" not in df.columns:
        df["distance_m"] = df.apply(
            lambda r: _haversine_m(float(r["origin_lat"]), float(r["origin_lon"]), float(r["dest_lat"]), float(r["dest_lon"])),
            axis=1,
        )

    dt = pd.to_datetime(df["timestamp"], errors="coerce")
    if dt.isna().any():
        raise ValueError("Invalid timestamp values in training dataset")

    df["hour"] = dt.dt.hour
    df["day_of_week"] = dt.dt.dayofweek
    X = df[["base_duration_s", "distance_m", "hour", "day_of_week"]]
    y = df["actual_duration_s"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    if progress_cb:
        progress_cb(50, "Training model")
    model = GradientBoostingRegressor(random_state=42)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    mae = float(mean_absolute_error(y_test, preds))
    mape = float(mean_absolute_percentage_error(y_test, preds)) if len(y_test) else 0.0

    version = datetime.utcnow().strftime("v%Y%m%d%H%M%S")
    model_path = ARTIFACT_DIR / f"model_{version}.joblib"
    joblib.dump(model, model_path)
    metrics = {
        "mae": mae,
        "mape": mape,
        "rows": int(len(df)),
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
    }
    feature_schema = ["base_duration_s", "distance_m", "hour", "day_of_week"]

    row = MLModel(
        version=version,
        artifact_path=str(model_path),
        feature_schema_json=json.dumps(feature_schema),
        training_data_ref=training_data_ref,
        metrics_json=json.dumps(metrics),
        status="TRAINED",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    if progress_cb:
        progress_cb(90, "Registering rollout")

    if get_latest_rollout(db) is None:
        set_rollout(db, active_version=version, canary_version=None, canary_percent=0, enabled=False)

    return {"model_version": version, "metrics": metrics, "artifact_path": str(model_path)}


def upload_actuals_csv(db: Session, *, filename: str, content: bytes) -> dict[str, Any]:
    df = pd.read_csv(BytesIO(content))
    required = {"origin_lat", "origin_lon", "dest_lat", "dest_lon", "timestamp_iso", "actual_duration_s"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    inserted = 0
    for _, row in df.iterrows():
        db.add(
            ActualTravelTime(
                origin_lat=float(row["origin_lat"]),
                origin_lon=float(row["origin_lon"]),
                dest_lat=float(row["dest_lat"]),
                dest_lon=float(row["dest_lon"]),
                timestamp_iso=str(row["timestamp_iso"]),
                actual_duration_s=float(row["actual_duration_s"]),
            )
        )
        inserted += 1
    db.commit()
    return {"filename": filename, "inserted_rows": inserted}


def compute_latest_ml_metrics(db: Session, *, persist_monitoring: bool = False) -> dict[str, Any]:
    now = datetime.utcnow()
    recent_predictions = db.execute(
        select(PredictionLog).where(PredictionLog.created_at >= now - timedelta(days=30)).order_by(PredictionLog.created_at.desc())
    ).scalars().all()
    actuals = db.execute(select(ActualTravelTime).where(ActualTravelTime.created_at >= now - timedelta(days=45))).scalars().all()

    actual_lookup: dict[tuple[float, float, float, float], list[float]] = {}
    for actual in actuals:
        key = (round(actual.origin_lat, 4), round(actual.origin_lon, 4), round(actual.dest_lat, 4), round(actual.dest_lon, 4))
        actual_lookup.setdefault(key, []).append(float(actual.actual_duration_s))

    paired: list[tuple[float, float, int]] = []
    for pred in recent_predictions:
        key = (round(pred.origin_lat, 4), round(pred.origin_lon, 4), round(pred.dest_lat, 4), round(pred.dest_lon, 4))
        actual_values = actual_lookup.get(key)
        if not actual_values:
            continue
        actual = actual_values[-1]
        hour = 0
        if pred.request_context_json:
            try:
                hour = int(json.loads(pred.request_context_json).get("hour", 0))
            except Exception:  # noqa: BLE001
                hour = 0
        paired.append((float(pred.predicted_duration_s), float(actual), hour))

    mae = None
    mape = None
    segmented = {"peak": {"mae": None, "mape": None, "count": 0}, "off_peak": {"mae": None, "mape": None, "count": 0}}
    if paired:
        y_pred = [p[0] for p in paired]
        y_true = [p[1] for p in paired]
        mae = float(mean_absolute_error(y_true, y_pred))
        mape = float(mean_absolute_percentage_error(y_true, y_pred))
        peak_pairs = [p for p in paired if p[2] in {7, 8, 9, 17, 18, 19, 20}]
        off_pairs = [p for p in paired if p[2] not in {7, 8, 9, 17, 18, 19, 20}]
        if peak_pairs:
            segmented["peak"] = {
                "mae": float(mean_absolute_error([p[1] for p in peak_pairs], [p[0] for p in peak_pairs])),
                "mape": float(mean_absolute_percentage_error([p[1] for p in peak_pairs], [p[0] for p in peak_pairs])),
                "count": len(peak_pairs),
            }
        if off_pairs:
            segmented["off_peak"] = {
                "mae": float(mean_absolute_error([p[1] for p in off_pairs], [p[0] for p in off_pairs])),
                "mape": float(mean_absolute_percentage_error([p[1] for p in off_pairs], [p[0] for p in off_pairs])),
                "count": len(off_pairs),
            }

    # Simple drift proxy: compare base_duration mean recent 7d vs previous 7d.
    pred_7 = [float(p.base_duration_s) for p in recent_predictions if p.created_at >= now - timedelta(days=7)]
    pred_prev = [float(p.base_duration_s) for p in recent_predictions if now - timedelta(days=14) <= p.created_at < now - timedelta(days=7)]
    if pred_7 and pred_prev:
        recent_mean = sum(pred_7) / len(pred_7)
        prev_mean = sum(pred_prev) / len(pred_prev)
        drift_score = abs(recent_mean - prev_mean) / max(prev_mean, 1.0)
    else:
        drift_score = 0.0

    needs_retrain = drift_score > get_settings().ml_drift_threshold
    result = {
        "generated_at": now.isoformat(),
        "paired_samples": len(paired),
        "mae": mae,
        "mape": mape,
        "segmented": segmented,
        "drift_score": drift_score,
        "needs_retrain": needs_retrain,
    }

    if persist_monitoring:
        db.add(
            MLMonitoring(
                drift_score=float(drift_score),
                mae=float(mae) if mae is not None else None,
                mape=float(mape) if mape is not None else None,
                segmented_json=json.dumps(segmented),
                needs_retrain=bool(needs_retrain),
            )
        )
        db.commit()

    return result


def retrain_if_needed(db: Session, *, progress_cb: Callable[[int, str], None] | None = None) -> dict[str, Any]:
    metrics = compute_latest_ml_metrics(db, persist_monitoring=True)
    recent_actuals_count = db.execute(select(func.count(ActualTravelTime.id))).scalar_one()
    enough_new_data = int(recent_actuals_count) >= get_settings().ml_retrain_min_rows
    if metrics["needs_retrain"] or enough_new_data:
        if progress_cb:
            progress_cb(30, "Retraining model based on drift/data threshold")
        model = train_and_register_model(db, dataset_path=None, progress_cb=progress_cb)
        return {"retrained": True, "reason": "drift_or_data", "model": model, "metrics": metrics}
    return {"retrained": False, "reason": "threshold_not_met", "metrics": metrics}


def latest_monitoring_snapshot(db: Session) -> dict[str, Any]:
    row = db.execute(select(MLMonitoring).order_by(MLMonitoring.created_at.desc(), MLMonitoring.id.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        return compute_latest_ml_metrics(db, persist_monitoring=False)
    return {
        "generated_at": row.created_at.isoformat(),
        "mae": row.mae,
        "mape": row.mape,
        "drift_score": row.drift_score,
        "needs_retrain": row.needs_retrain,
        "segmented": json.loads(row.segmented_json) if row.segmented_json else {},
    }


def choose_model_version_for_prediction(db: Session) -> str | None:
    rollout = db.execute(select(ModelRollout).order_by(ModelRollout.created_at.desc(), ModelRollout.id.desc()).limit(1)).scalar_one_or_none()
    if rollout is None:
        model = db.execute(select(MLModel).where(MLModel.status.in_(["TRAINED", "DEPLOYED"])).order_by(MLModel.created_at.desc())).scalar_one_or_none()
        return model.version if model else None
    if rollout.enabled and rollout.canary_version and rollout.canary_percent > 0:
        bucket = random.randint(1, 100)
        if bucket <= rollout.canary_percent:
            return rollout.canary_version
    return rollout.active_version
