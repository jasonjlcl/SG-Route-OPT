from io import BytesIO
from types import SimpleNamespace

from app.services import scale_guardrails


def _upload_dataset(client, *, stop_count: int) -> int:
    rows = ["stop_ref,address,demand,service_time_min"]
    for idx in range(1, stop_count + 1):
        rows.append(f"S{idx},10 Bayfront Avenue,1,5")
    content = ("\n".join(rows) + "\n").encode("utf-8")
    response = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("stops.csv", BytesIO(content), "text/csv")},
        data={"exclude_invalid": "true"},
    )
    assert response.status_code == 200
    return int(response.json()["dataset_id"])


def test_datasets_optimize_rejects_when_max_stops_exceeded(client, monkeypatch):
    dataset_id = _upload_dataset(client, stop_count=2)
    monkeypatch.setattr(
        scale_guardrails,
        "get_settings",
        lambda: SimpleNamespace(optimize_max_stops=1, optimize_max_matrix_elements=9999),
    )

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/optimize",
        json={
            "depot_lat": 1.3521,
            "depot_lon": 103.8198,
            "fleet": {"num_vehicles": 1, "capacity": 4},
            "workday_start": "08:00",
            "workday_end": "18:00",
            "solver": {"solver_time_limit_s": 8, "allow_drop_visits": True},
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "OPTIMIZE_MAX_STOPS_EXCEEDED"
    assert "split the dataset" in body["message"].lower()
    assert body["details"]["dataset_id"] == dataset_id
    assert body["details"]["stop_count"] == 2
    assert body["details"]["max_stops"] == 1


def test_jobs_optimize_rejects_when_matrix_size_exceeded(client, monkeypatch):
    dataset_id = _upload_dataset(client, stop_count=2)
    monkeypatch.setattr(
        scale_guardrails,
        "get_settings",
        lambda: SimpleNamespace(optimize_max_stops=10, optimize_max_matrix_elements=5),
    )

    response = client.post(
        "/api/v1/jobs/optimize",
        json={
            "dataset_id": dataset_id,
            "depot_lat": 1.3521,
            "depot_lon": 103.8198,
            "fleet_config": {"num_vehicles": 1, "capacity": 4},
            "workday_start": "08:00",
            "workday_end": "18:00",
            "solver": {"solver_time_limit_s": 8, "allow_drop_visits": True},
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "OPTIMIZE_MAX_MATRIX_ELEMENTS_EXCEEDED"
    assert "matrix size limit" in body["message"].lower()
    assert body["details"]["dataset_id"] == dataset_id
    assert body["details"]["estimated_matrix_elements"] == 6
    assert body["details"]["max_matrix_elements"] == 5


def test_optimize_ab_test_rejects_when_scale_exceeded(client, monkeypatch):
    dataset_id = _upload_dataset(client, stop_count=3)
    monkeypatch.setattr(
        scale_guardrails,
        "get_settings",
        lambda: SimpleNamespace(optimize_max_stops=2, optimize_max_matrix_elements=9999),
    )

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/optimize/ab-test",
        json={
            "depot_lat": 1.3521,
            "depot_lon": 103.8198,
            "fleet": {"num_vehicles": 1, "capacity": 4},
            "workday_start": "08:00",
            "workday_end": "18:00",
            "solver": {"solver_time_limit_s": 8, "allow_drop_visits": True},
            "model_version": None,
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "OPTIMIZE_MAX_STOPS_EXCEEDED"
    assert body["details"]["dataset_id"] == dataset_id
    assert body["details"]["stop_count"] == 3
    assert body["details"]["max_stops"] == 2
