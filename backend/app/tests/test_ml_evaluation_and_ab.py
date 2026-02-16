from __future__ import annotations

import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd

from app.models import ActualTravelTime
from app.services.ml_ops import set_rollout, train_and_register_model
from app.utils.db import SessionLocal


def test_ml_evaluation_compare_endpoint(client):
    rows = []
    for i in range(80):
        hour = i % 24
        rows.append(
            {
                "origin_lat": 1.30,
                "origin_lon": 103.80,
                "dest_lat": 1.34,
                "dest_lon": 103.86,
                "base_duration_s": 700 + (i % 25) * 9,
                "distance_m": 3800 + (i % 17) * 90,
                "timestamp": f"2025-01-{(i % 28) + 1:02d}T{hour:02d}:00:00",
                "actual_duration_s": 780 + (i % 25) * 10 + (45 if hour in {7, 8, 9, 17, 18, 19} else 0),
            }
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "train.csv"
        pd.DataFrame(rows).to_csv(csv_path, index=False)

        db = SessionLocal()
        try:
            train_result = train_and_register_model(db, dataset_path=str(csv_path))
            set_rollout(db, active_version=train_result["model_version"], enabled=False)

            for row in rows:
                db.add(
                    ActualTravelTime(
                        origin_lat=float(row["origin_lat"]),
                        origin_lon=float(row["origin_lon"]),
                        dest_lat=float(row["dest_lat"]),
                        dest_lon=float(row["dest_lon"]),
                        timestamp_iso=str(row["timestamp"]),
                        actual_duration_s=float(row["actual_duration_s"]),
                    )
                )
            db.commit()
        finally:
            db.close()

    resp = client.get("/api/v1/ml/evaluation/compare", params={"days": 365, "limit": 1000})
    assert resp.status_code == 200
    body = resp.json()
    assert body["samples"] > 0
    assert len(body["kpis"]) >= 5
    assert any(item["key"] == "mae_s" for item in body["kpis"])


def test_optimize_ab_simulation_job(client):
    csv_content = """stop_ref,address,demand,service_time_min,tw_start,tw_end
S1,10 Bayfront Avenue,1,5,09:00,12:00
S2,1 Raffles Place,1,5,09:00,13:00
S3,50 Nanyang Ave,1,5,10:00,15:00
S4,1 HarbourFront Walk,1,5,10:00,16:00
"""
    upload = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("stops.csv", BytesIO(csv_content.encode("utf-8")), "text/csv")},
        data={"exclude_invalid": "true"},
    )
    assert upload.status_code == 200
    dataset_id = upload.json()["dataset_id"]

    geocode = client.post(f"/api/v1/datasets/{dataset_id}/geocode", params={"sync": "true"})
    assert geocode.status_code == 200

    ab = client.post(
        f"/api/v1/datasets/{dataset_id}/optimize/ab-test",
        json={
            "depot_lat": 1.3521,
            "depot_lon": 103.8198,
            "fleet": {"num_vehicles": 2, "capacity": 4},
            "workday_start": "08:00",
            "workday_end": "18:00",
            "solver": {"solver_time_limit_s": 8, "allow_drop_visits": True},
        },
    )
    assert ab.status_code == 200
    job_id = ab.json()["job_id"]

    status = client.get(f"/api/v1/jobs/{job_id}")
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] in {"SUCCEEDED", "FAILED"}
    assert payload["status"] == "SUCCEEDED"
    result_ref = payload["result_ref"] or {}
    assert "comparison" in result_ref
    assert len(result_ref["comparison"]) >= 3
    assert result_ref.get("file_path")
    assert Path(result_ref["file_path"]).exists()

