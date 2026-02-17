from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from app.ml_uplift import UPLIFT_ARTIFACT_DIR
from app.ml_uplift.features import clamp_factor
from app.ml_uplift.schema import (
    UPLIFT_CATEGORICAL_COLUMNS,
    UPLIFT_FEATURE_COLUMNS,
    UPLIFT_NUMERIC_COLUMNS,
    UPLIFT_SAMPLE_COLUMNS,
)
from app.ml_uplift.storage import read_samples_df


LATEST_MODEL_FILE = UPLIFT_ARTIFACT_DIR / "latest_model.joblib"
LATEST_VERSION_FILE = UPLIFT_ARTIFACT_DIR / "latest_version.txt"
LATEST_METRICS_FILE = UPLIFT_ARTIFACT_DIR / "latest_metrics.json"


def _safe_mape(y_true: pd.Series, y_pred: pd.Series) -> float:
    pairs = [(a, p) for a, p in zip(y_true.tolist(), y_pred.tolist()) if abs(float(a)) > 1e-9]
    if not pairs:
        return 0.0
    return float(sum(abs((float(p) - float(a)) / float(a)) for a, p in pairs) / len(pairs))


def _duration_metrics(y_true: pd.Series, y_pred: pd.Series) -> dict[str, float]:
    if len(y_true) == 0:
        return {"mae_s": 0.0, "mape_pct": 0.0}
    mae_s = float((y_pred - y_true).abs().mean())
    mape_pct = float(_safe_mape(y_true, y_pred) * 100.0)
    return {"mae_s": mae_s, "mape_pct": mape_pct}


def _improvement_pct(baseline: float, model: float) -> float | None:
    if abs(float(baseline)) < 1e-9:
        return None
    return float(((float(baseline) - float(model)) / abs(float(baseline))) * 100.0)


def _segment_metrics(df: pd.DataFrame, *, baseline_col: str, model_col: str) -> list[dict[str, Any]]:
    if df.empty:
        return []

    def _metrics_for(segment_name: str, segment_df: pd.DataFrame) -> dict[str, Any]:
        baseline_m = _duration_metrics(segment_df["duration_s"], segment_df[baseline_col])
        model_m = _duration_metrics(segment_df["duration_s"], segment_df[model_col])
        return {
            "segment": segment_name,
            "count": int(len(segment_df)),
            "baseline_mae_s": float(baseline_m["mae_s"]),
            "ml_mae_s": float(model_m["mae_s"]),
            "baseline_mape_pct": float(baseline_m["mape_pct"]),
            "ml_mape_pct": float(model_m["mape_pct"]),
            "mae_improvement_pct": _improvement_pct(baseline_m["mae_s"], model_m["mae_s"]),
            "mape_improvement_pct": _improvement_pct(baseline_m["mape_pct"], model_m["mape_pct"]),
        }

    segments: list[tuple[str, pd.DataFrame]] = [
        ("peak", df[df["time_bucket"].isin([7, 8, 9, 17, 18, 19, 20])]),
        ("off_peak", df[~df["time_bucket"].isin([7, 8, 9, 17, 18, 19, 20])]),
        ("weekday", df[df["dow_bucket"] <= 4]),
        ("weekend", df[df["dow_bucket"] >= 5]),
    ]
    return [_metrics_for(name, seg_df) for name, seg_df in segments]


def evaluate_uplift_predictions(df: pd.DataFrame, *, pred_factor: pd.Series) -> dict[str, Any]:
    if df.empty:
        return {
            "samples": 0,
            "baseline_metrics": {"mae_s": 0.0, "mape_pct": 0.0},
            "ml_metrics": {"mae_s": 0.0, "mape_pct": 0.0},
            "segments": [],
        }

    factors = pred_factor.apply(lambda x: clamp_factor(float(x)))
    eval_df = df.copy()
    eval_df["baseline_duration_s"] = eval_df["static_duration_s"].astype(float)
    eval_df["ml_duration_s"] = eval_df["static_duration_s"].astype(float) * factors.astype(float)

    baseline_metrics = _duration_metrics(eval_df["duration_s"], eval_df["baseline_duration_s"])
    ml_metrics = _duration_metrics(eval_df["duration_s"], eval_df["ml_duration_s"])

    return {
        "samples": int(len(eval_df)),
        "baseline_metrics": baseline_metrics,
        "ml_metrics": ml_metrics,
        "mape_improvement_pct": _improvement_pct(baseline_metrics["mape_pct"], ml_metrics["mape_pct"]),
        "mae_improvement_pct": _improvement_pct(baseline_metrics["mae_s"], ml_metrics["mae_s"]),
        "segments": _segment_metrics(eval_df, baseline_col="baseline_duration_s", model_col="ml_duration_s"),
    }


def _validate_training_frame(df: pd.DataFrame) -> pd.DataFrame:
    required = set(UPLIFT_SAMPLE_COLUMNS)
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    cast_df = df.copy()
    cast_df["distance_m"] = pd.to_numeric(cast_df["distance_m"], errors="coerce")
    cast_df["time_bucket"] = pd.to_numeric(cast_df["time_bucket"], errors="coerce")
    cast_df["dow_bucket"] = pd.to_numeric(cast_df["dow_bucket"], errors="coerce")
    cast_df["static_duration_s"] = pd.to_numeric(cast_df["static_duration_s"], errors="coerce")
    cast_df["duration_s"] = pd.to_numeric(cast_df["duration_s"], errors="coerce")
    cast_df["congestion_factor"] = pd.to_numeric(cast_df["congestion_factor"], errors="coerce")
    cast_df["departure_dt"] = pd.to_datetime(cast_df["departure_time_iso"], errors="coerce")
    cast_df = cast_df.dropna(
        subset=[
            "origin_zone",
            "dest_zone",
            "distance_m",
            "time_bucket",
            "dow_bucket",
            "static_duration_s",
            "duration_s",
            "congestion_factor",
            "departure_dt",
        ]
    )
    cast_df = cast_df[cast_df["static_duration_s"] > 0]
    cast_df = cast_df[cast_df["duration_s"] > 0]
    cast_df = cast_df.sort_values("departure_dt").reset_index(drop=True)
    return cast_df


def _time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n = len(df)
    if n < 12:
        raise ValueError("Need at least 12 uplift samples for time-based split")

    train_end = max(1, int(n * 0.7))
    val_end = max(train_end + 1, int(n * 0.85))
    if val_end >= n:
        val_end = n - 1
    if train_end >= val_end:
        train_end = max(1, val_end - 1)

    train_df = df.iloc[:train_end].copy()
    val_df = df.iloc[train_end:val_end].copy()
    test_df = df.iloc[val_end:].copy()
    if train_df.empty or val_df.empty or test_df.empty:
        raise ValueError("Unable to create non-empty train/val/test time split for uplift model")
    return train_df, val_df, test_df


def train_uplift_model(
    *,
    samples_path: str | Path | None = None,
    min_rows: int = 120,
) -> dict[str, Any]:
    raw_df = read_samples_df(samples_path)
    df = _validate_training_frame(raw_df)
    if len(df) < int(min_rows):
        raise ValueError(f"Insufficient uplift samples: {len(df)} rows, requires at least {int(min_rows)}")

    train_df, val_df, test_df = _time_split(df)
    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), UPLIFT_CATEGORICAL_COLUMNS),
            ("num", "passthrough", UPLIFT_NUMERIC_COLUMNS),
        ]
    )
    model = RandomForestRegressor(
        n_estimators=240,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1,
    )
    pipeline = Pipeline(
        steps=[
            ("features", preprocessor),
            ("model", model),
        ]
    )

    X_train = train_df[UPLIFT_FEATURE_COLUMNS]
    y_train = train_df["congestion_factor"].astype(float)
    pipeline.fit(X_train, y_train)

    val_pred = pd.Series(pipeline.predict(val_df[UPLIFT_FEATURE_COLUMNS]), index=val_df.index)
    test_pred = pd.Series(pipeline.predict(test_df[UPLIFT_FEATURE_COLUMNS]), index=test_df.index)
    val_eval = evaluate_uplift_predictions(val_df, pred_factor=val_pred)
    test_eval = evaluate_uplift_predictions(test_df, pred_factor=test_pred)

    version = datetime.utcnow().strftime("uplift_%Y%m%d%H%M%S%f")
    version_dir = UPLIFT_ARTIFACT_DIR / version
    version_dir.mkdir(parents=True, exist_ok=True)
    model_path = version_dir / "model.joblib"

    artifact = {
        "version": version,
        "feature_columns": UPLIFT_FEATURE_COLUMNS,
        "created_at": datetime.utcnow().isoformat(),
        "pipeline": pipeline,
    }
    joblib.dump(artifact, model_path)
    joblib.dump(artifact, LATEST_MODEL_FILE)
    LATEST_VERSION_FILE.write_text(version, encoding="utf-8")

    metrics = {
        "version": version,
        "rows": int(len(df)),
        "train_rows": int(len(train_df)),
        "val_rows": int(len(val_df)),
        "test_rows": int(len(test_df)),
        "target": "congestion_factor",
        "split_type": "time_based_70_15_15",
        "validation": val_eval,
        "test": test_eval,
        "success_criterion": {
            "target_mape_improvement_pct_range": "10-30",
            "test_mape_improvement_pct": test_eval.get("mape_improvement_pct"),
            "test_mae_improvement_pct": test_eval.get("mae_improvement_pct"),
        },
    }

    metrics_path = version_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    LATEST_METRICS_FILE.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    return {
        "version": version,
        "model_path": str(model_path),
        "metrics_path": str(metrics_path),
        "metrics": metrics,
    }


def resolve_uplift_model_path(version: str | None = None) -> Path | None:
    if version:
        candidate = UPLIFT_ARTIFACT_DIR / version / "model.joblib"
        return candidate if candidate.exists() else None
    if LATEST_MODEL_FILE.exists():
        return LATEST_MODEL_FILE
    if LATEST_VERSION_FILE.exists():
        candidate = UPLIFT_ARTIFACT_DIR / LATEST_VERSION_FILE.read_text(encoding="utf-8").strip() / "model.joblib"
        if candidate.exists():
            return candidate
    return None


def load_uplift_artifact(version: str | None = None) -> dict[str, Any] | None:
    path = resolve_uplift_model_path(version=version)
    if path is None or not path.exists():
        return None
    loaded = joblib.load(path)
    if not isinstance(loaded, dict):
        return None
    if "pipeline" not in loaded:
        return None
    return loaded

