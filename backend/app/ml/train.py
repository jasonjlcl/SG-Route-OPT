from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split


ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Train baseline route duration model")
    parser.add_argument("--input", required=True, help="Path to historical CSV")
    args = parser.parse_args()

    df = pd.read_csv(args.input)

    required_cols = {
        "origin_lat",
        "origin_lon",
        "dest_lat",
        "dest_lon",
        "base_duration_s",
        "timestamp",
        "actual_duration_s",
    }
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    if "distance_m" not in df.columns:
        df["distance_m"] = df.apply(
            lambda r: haversine_m(r["origin_lat"], r["origin_lon"], r["dest_lat"], r["dest_lon"]),
            axis=1,
        )

    dt = pd.to_datetime(df["timestamp"], errors="coerce")
    if dt.isna().any():
        raise ValueError("Invalid timestamp values")

    df["hour"] = dt.dt.hour
    df["day_of_week"] = dt.dt.dayofweek

    X = df[["base_duration_s", "distance_m", "hour", "day_of_week"]]
    y = df["actual_duration_s"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = GradientBoostingRegressor(random_state=42)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)

    version = datetime.utcnow().strftime("v%Y%m%d%H%M%S")
    model_path = ARTIFACT_DIR / f"model_{version}.joblib"
    meta_path = ARTIFACT_DIR / f"model_{version}.meta.json"

    joblib.dump(model, model_path)
    meta_path.write_text(
        json.dumps(
            {
                "model_version": version,
                "trained_at": datetime.utcnow().isoformat(),
                "mae": float(mae),
                "features": ["base_duration_s", "distance_m", "hour", "day_of_week"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Saved model: {model_path}")
    print(f"Saved metadata: {meta_path}")
    print(f"MAE: {mae:.2f}")


if __name__ == "__main__":
    main()
