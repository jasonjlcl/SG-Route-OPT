from io import BytesIO
import time


def _wait_job(client, job_id: str, timeout_s: float = 20.0):
    started = time.time()
    while time.time() - started < timeout_s:
        resp = client.get(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in {"SUCCEEDED", "FAILED", "CANCELED", "CANCELLED"}:
            return body
        time.sleep(0.25)
    raise AssertionError(f"Job {job_id} did not complete in {timeout_s}s")


def test_geocode_job_lifecycle(client):
    csv_content = """stop_ref,address,demand,service_time_min
S1,10 Bayfront Avenue,1,5
S2,1 Raffles Place,1,5
"""
    upload = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("stops.csv", BytesIO(csv_content.encode("utf-8")), "text/csv")},
        data={"exclude_invalid": "true"},
    )
    dataset_id = upload.json()["dataset_id"]

    start = client.post(f"/api/v1/datasets/{dataset_id}/geocode")
    assert start.status_code == 200
    job_id = start.json()["job_id"]

    done = _wait_job(client, job_id)
    assert done["status"] == "SUCCEEDED"
    assert done["progress"] == 100


def test_optimize_job_lifecycle(client):
    csv_content = """stop_ref,address,demand,service_time_min,tw_start,tw_end
S1,10 Bayfront Avenue,1,5,09:00,12:00
S2,1 Raffles Place,1,5,10:00,15:00
"""
    upload = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("stops.csv", BytesIO(csv_content.encode("utf-8")), "text/csv")},
        data={"exclude_invalid": "true"},
    )
    dataset_id = upload.json()["dataset_id"]
    client.post(f"/api/v1/datasets/{dataset_id}/geocode", params={"sync": "true"})

    start = client.post(
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
    assert start.status_code == 200
    job_id = start.json()["job_id"]
    done = _wait_job(client, job_id, timeout_s=30.0)
    assert done["status"] == "SUCCEEDED"
    assert done["result_ref"] is not None
    assert done["result_ref"].get("plan_id")


def test_optimize_pipeline_jobs_endpoint(client):
    csv_content = """stop_ref,address,demand,service_time_min,tw_start,tw_end
S1,10 Bayfront Avenue,1,5,09:00,12:00
S2,1 Raffles Place,1,5,10:00,15:00
"""
    upload = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("stops.csv", BytesIO(csv_content.encode("utf-8")), "text/csv")},
        data={"exclude_invalid": "true"},
    )
    dataset_id = upload.json()["dataset_id"]

    start = client.post(
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
    assert start.status_code == 200
    job_id = start.json()["job_id"]

    done = _wait_job(client, job_id, timeout_s=30.0)
    assert done["status"] == "SUCCEEDED"
    assert done.get("current_step") == "GENERATE_EXPORTS"
    assert done.get("result_ref", {}).get("plan_id")
    assert "driver_pack" in (done.get("result_ref") or {})
