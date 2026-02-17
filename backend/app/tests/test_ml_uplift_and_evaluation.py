from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from app.utils.settings import get_settings


CSV_CONTENT = """stop_ref,address,demand,service_time_min,tw_start,tw_end
S1,10 Bayfront Avenue,1,5,09:00,12:00
S2,1 Raffles Place,1,5,10:00,15:00
"""


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _create_dataset_and_geocode(client) -> int:
    upload = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("stops.csv", BytesIO(CSV_CONTENT.encode("utf-8")), "text/csv")},
        data={"exclude_invalid": "true"},
    )
    assert upload.status_code == 200
    dataset_id = int(upload.json()["dataset_id"])
    geocode = client.post(f"/api/v1/datasets/{dataset_id}/geocode", params={"sync": "true"})
    assert geocode.status_code == 200
    return dataset_id


def test_optimize_eta_source_ml_uplift(client, monkeypatch):
    monkeypatch.setenv("FEATURE_ML_UPLIFT", "true")
    get_settings.cache_clear()

    class FakeUpliftService:
        @property
        def enabled(self):
            return True

        @property
        def model_version(self):
            return "uplift_test_v1"

        def model_available(self):
            return True

        def build_inference_row(self, **kwargs):
            return kwargs

        def predict_factors(self, feature_rows):
            return [1.15 for _ in feature_rows]

        def collect_google_leg_samples(self, **kwargs):
            return 0

    monkeypatch.setattr("app.services.optimization.get_ml_uplift_service", lambda: FakeUpliftService())

    dataset_id = _create_dataset_and_geocode(client)
    optimize = client.post(
        f"/api/v1/datasets/{dataset_id}/optimize?sync=true",
        json={
            "depot_lat": 1.3521,
            "depot_lon": 103.8198,
            "fleet": {"num_vehicles": 1, "capacity": 4},
            "workday_start": "08:00",
            "workday_end": "18:00",
            "solver": {"solver_time_limit_s": 8, "allow_drop_visits": True},
            "use_live_traffic": False,
        },
    )
    assert optimize.status_code == 200
    result = optimize.json()
    assert result["eta_source"] == "ml_uplift"

    plan = client.get(f"/api/v1/plans/{result['plan_id']}")
    assert plan.status_code == 200
    assert plan.json()["eta_source"] == "ml_uplift"


def test_evaluation_prediction_and_run_job(client, monkeypatch):
    monkeypatch.setenv("FEATURE_EVAL_DASHBOARD", "true")
    get_settings.cache_clear()

    dataset_id = _create_dataset_and_geocode(client)

    prediction = client.get("/api/v1/evaluation/prediction", params={"limit": 1000})
    assert prediction.status_code == 200
    body = prediction.json()
    assert body["baseline"] == "static_duration_s"

    run = client.post(
        "/api/v1/evaluation/run",
        json={
            "dataset_id": dataset_id,
            "depot_lat": 1.3521,
            "depot_lon": 103.8198,
            "fleet_config": {"num_vehicles": 1, "capacity": 4},
            "workday_start": "08:00",
            "workday_end": "18:00",
            "solver": {"solver_time_limit_s": 8, "allow_drop_visits": True},
            "sample_limit": 1000,
        },
    )
    assert run.status_code == 200
    job_id = run.json()["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}")
    assert job.status_code == 200
    payload = job.json()
    assert payload["status"] == "SUCCEEDED"
    result_ref = payload["result_ref"] or {}
    assert "prediction" in result_ref
    assert "planning" in result_ref
    assert result_ref.get("file_path")
    assert Path(result_ref["file_path"]).exists()
