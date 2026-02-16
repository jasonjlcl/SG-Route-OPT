from __future__ import annotations

import json
import math
import random
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import joblib
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ActualTravelTime, MLModel, MLMonitoring, ModelRollout, PredictionLog
from app.services.ml_features import FEATURE_COLUMNS, build_feature_dict
from app.services.vertex_ai import register_local_model_to_vertex
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
            "artifact_gcs_uri": row.artifact_gcs_uri,
            "vertex_model_resource": row.vertex_model_resource,
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
    force_vertex: bool | None = None,
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

    df["timestamp_dt"] = dt
    feature_rows = [
        build_feature_dict(
            base_duration_s=float(row["base_duration_s"]),
            distance_m=float(row["distance_m"]),
            depart_dt=row["timestamp_dt"].to_pydatetime() if hasattr(row["timestamp_dt"], "to_pydatetime") else row["timestamp_dt"],
            origin_lat=float(row["origin_lat"]),
            origin_lon=float(row["origin_lon"]),
            dest_lat=float(row["dest_lat"]),
            dest_lon=float(row["dest_lon"]),
        )
        for _, row in df.iterrows()
    ]

    feature_df = pd.DataFrame(feature_rows)
    X = feature_df[FEATURE_COLUMNS].astype(float)
    y = df["actual_duration_s"].astype(float)

    # Time-based split for stronger evaluation rigor.
    order = df["timestamp_dt"].sort_values().index
    split_idx = int(len(order) * 0.8)
    if split_idx <= 0:
        split_idx = max(1, len(order) - 1)
    if split_idx >= len(order):
        split_idx = len(order) - 1
    if split_idx <= 0:
        raise ValueError("Not enough rows to create train/test split")

    train_idx = order[:split_idx]
    test_idx = order[split_idx:]

    X_train = X.loc[train_idx]
    y_train = y.loc[train_idx]
    X_test = X.loc[test_idx]
    y_test = y.loc[test_idx]

    if progress_cb:
        progress_cb(50, "Training model")
    model = GradientBoostingRegressor(random_state=42)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    mae = float(mean_absolute_error(y_test, preds))
    mape = float(mean_absolute_percentage_error(y_test, preds)) if len(y_test) else 0.0
    rmse = float(math.sqrt(((y_test.to_numpy() - preds) ** 2).mean())) if len(y_test) else 0.0
    errors = preds - y_test.to_numpy()
    abs_errors = abs(errors)
    bias_s = float(errors.mean()) if len(errors) else 0.0
    p90_abs_error_s = float(pd.Series(abs_errors).quantile(0.9)) if len(abs_errors) else 0.0
    p50_abs_error_s = float(pd.Series(abs_errors).quantile(0.5)) if len(abs_errors) else 0.0
    residual_std_s = float(pd.Series(errors).std(ddof=0)) if len(errors) else 0.0

    # Include microseconds to avoid version collisions for rapid consecutive train jobs.
    version = datetime.utcnow().strftime("v%Y%m%d%H%M%S%f")
    version_dir = ARTIFACT_DIR / version
    version_dir.mkdir(parents=True, exist_ok=True)
    model_path = version_dir / "model.pkl"
    joblib.dump(model, model_path)
    metrics = {
        "mae": mae,
        "mape": mape,
        "rmse": rmse,
        "bias_s": bias_s,
        "p90_abs_error_s": p90_abs_error_s,
        "p50_abs_error_s": p50_abs_error_s,
        "residual_std_s": residual_std_s,
        "uncertainty_p90_s": p90_abs_error_s,
        "uncertainty_p50_s": p50_abs_error_s,
        "rows": int(len(df)),
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "split_type": "time_based_80_20",
    }
    feature_schema = FEATURE_COLUMNS

    (version_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (version_dir / "feature_schema.json").write_text(json.dumps(feature_schema, indent=2), encoding="utf-8")
    (version_dir / "version.txt").write_text(version, encoding="utf-8")

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

    use_vertex = get_settings().feature_vertex_ai if force_vertex is None else force_vertex
    vertex_metadata: dict[str, str] | None = None
    if use_vertex:
        if progress_cb:
            progress_cb(80, "Registering model in Vertex AI")
        try:
            vertex_metadata = register_local_model_to_vertex(model_version=version, model_bytes=model_path.read_bytes())
            if vertex_metadata:
                row.artifact_gcs_uri = vertex_metadata.get("artifact_gcs_uri")
                row.vertex_model_resource = vertex_metadata.get("vertex_model_resource")
                row.status = "VERTEX_REGISTERED"
                db.commit()
                db.refresh(row)
        except Exception as exc:  # noqa: BLE001
            metrics["vertex_error"] = str(exc)
            row.metrics_json = json.dumps(metrics)
            db.commit()
            db.refresh(row)

    if progress_cb:
        progress_cb(90, "Registering rollout")

    if get_latest_rollout(db) is None:
        set_rollout(db, active_version=version, canary_version=None, canary_percent=0, enabled=False)

    return {
        "model_version": version,
        "metrics": metrics,
        "artifact_path": str(model_path),
        "artifact_gcs_uri": row.artifact_gcs_uri,
        "vertex_model_resource": row.vertex_model_resource,
    }


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


def get_model_metadata(db: Session, version: str) -> dict[str, Any] | None:
    row = db.execute(select(MLModel).where(MLModel.version == version)).scalar_one_or_none()
    if row is None:
        return None
    return {
        "version": row.version,
        "artifact_path": row.artifact_path,
        "artifact_gcs_uri": row.artifact_gcs_uri,
        "vertex_model_resource": row.vertex_model_resource,
        "status": row.status,
        "metrics": json.loads(row.metrics_json) if row.metrics_json else {},
    }


def generate_drift_report(
    db: Session,
    *,
    days: int = 30,
    limit: int = 5000,
) -> dict[str, Any]:
    from app.services.ml_evaluation import compare_baseline_vs_model

    rollout = get_latest_rollout(db) or {}
    active_version = rollout.get("active_version")
    evaluation = compare_baseline_vs_model(db, days=days, limit=limit, model_version=active_version)
    kpi_map = {row.get("key"): row for row in evaluation.get("kpis", [])}

    baseline_mae = float((kpi_map.get("mae_s") or {}).get("baseline") or 0.0)
    model_mae = float((kpi_map.get("mae_s") or {}).get("model") or 0.0)
    baseline_mape = float((kpi_map.get("mape_pct") or {}).get("baseline") or 0.0)
    model_mape = float((kpi_map.get("mape_pct") or {}).get("model") or 0.0)

    drift_threshold = float(get_settings().ml_drift_threshold)
    mae_drift_ratio = ((model_mae - baseline_mae) / max(baseline_mae, 1.0)) if baseline_mae > 0 else 0.0

    segment_bias = 0.0
    for segment in evaluation.get("segments", []):
        b = float(segment.get("baseline_mae_s") or 0.0)
        m = float(segment.get("model_mae_s") or 0.0)
        if b <= 0:
            continue
        segment_bias = max(segment_bias, abs((m - b) / b))

    drift_flagged = bool(mae_drift_ratio > drift_threshold or segment_bias > drift_threshold)
    actual_count = int(db.execute(select(func.count(ActualTravelTime.id))).scalar_one())
    enough_new_actuals = actual_count >= int(get_settings().ml_retrain_min_rows)
    retrain_recommended = bool(drift_flagged and enough_new_actuals)

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "days": days,
        "samples": int(evaluation.get("samples") or 0),
        "active_model_version": active_version,
        "baseline_mae_s": baseline_mae,
        "model_mae_s": model_mae,
        "baseline_mape_pct": baseline_mape,
        "model_mape_pct": model_mape,
        "mae_drift_ratio": mae_drift_ratio,
        "segment_bias_max": segment_bias,
        "threshold": drift_threshold,
        "drift_flagged": drift_flagged,
        "actual_rows": actual_count,
        "enough_new_actuals": enough_new_actuals,
        "retrain_recommended": retrain_recommended,
        "segments": evaluation.get("segments", []),
    }
    db.add(
        MLMonitoring(
            drift_score=float(max(mae_drift_ratio, segment_bias, 0.0)),
            mae=model_mae if model_mae > 0 else None,
            mape=model_mape if model_mape > 0 else None,
            segmented_json=json.dumps({"segments": report["segments"]}),
            needs_retrain=retrain_recommended,
        )
    )
    db.commit()
    return report


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
