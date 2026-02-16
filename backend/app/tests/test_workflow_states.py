from io import BytesIO

from app.models import Plan
from app.utils.db import SessionLocal


def _upload_simple_dataset(client, csv_content: str) -> int:
    response = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("stops.csv", BytesIO(csv_content.encode("utf-8")), "text/csv")},
        data={"exclude_invalid": "true"},
    )
    assert response.status_code == 200
    return int(response.json()["dataset_id"])


def test_geocode_state_needs_attention_when_failed_stops(client, monkeypatch):
    class DummyClient:
        def search(self, query: str):
            if "No Result" in query:
                return {"results": []}
            return {"results": [{"LATITUDE": "1.3001", "LONGITUDE": "103.8002", "ADDRESS": query, "POSTAL": "123456"}]}

    monkeypatch.setattr("app.services.geocoding.get_onemap_client", lambda: DummyClient())

    dataset_id = _upload_simple_dataset(
        client,
        "stop_ref,address,demand,service_time_min\nS1,1 Raffles Place,1,5\nS2,No Result Street,1,5\n",
    )
    geocode_response = client.post(f"/api/v1/datasets/{dataset_id}/geocode", params={"sync": "true"})
    assert geocode_response.status_code == 200

    summary_response = client.get(f"/api/v1/datasets/{dataset_id}")
    assert summary_response.status_code == 200
    body = summary_response.json()
    assert body["geocode_state"] == "NEEDS_ATTENTION"
    assert int(body["geocode_counts"].get("FAILED", 0)) >= 1


def test_optimize_state_complete_only_for_success_or_partial(client):
    dataset_id = _upload_simple_dataset(client, "stop_ref,address,demand,service_time_min\nS1,10 Bayfront Avenue,1,5\n")

    db = SessionLocal()
    try:
        db.add(Plan(dataset_id=dataset_id, depot_lat=1.3521, depot_lon=103.8198, num_vehicles=1, status="INFEASIBLE"))
        db.commit()
    finally:
        db.close()

    summary_infeasible = client.get(f"/api/v1/datasets/{dataset_id}")
    assert summary_infeasible.status_code == 200
    assert summary_infeasible.json()["optimize_state"] == "NEEDS_ATTENTION"

    db = SessionLocal()
    try:
        db.add(Plan(dataset_id=dataset_id, depot_lat=1.3521, depot_lon=103.8198, num_vehicles=1, status="PARTIAL"))
        db.commit()
    finally:
        db.close()

    summary_partial = client.get(f"/api/v1/datasets/{dataset_id}")
    assert summary_partial.status_code == 200
    assert summary_partial.json()["optimize_state"] == "COMPLETE"
