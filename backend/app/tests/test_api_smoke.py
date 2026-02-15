from io import BytesIO


def test_api_smoke_flow(client):
    csv_content = """stop_ref,address,demand,service_time_min,tw_start,tw_end
S1,10 Bayfront Avenue,1,5,09:00,12:00
S2,1 Raffles Place,1,5,10:00,15:00
S3,50 Nanyang Ave,1,5,09:30,16:30
"""

    upload_resp = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("stops.csv", BytesIO(csv_content.encode("utf-8")), "text/csv")},
        data={"exclude_invalid": "true"},
    )
    assert upload_resp.status_code == 200
    dataset_id = upload_resp.json()["dataset_id"]

    geocode_resp = client.post(f"/api/v1/datasets/{dataset_id}/geocode")
    assert geocode_resp.status_code == 200
    assert geocode_resp.json()["success_count"] >= 1

    optimize_resp = client.post(
        f"/api/v1/datasets/{dataset_id}/optimize",
        json={
            "depot_lat": 1.3521,
            "depot_lon": 103.8198,
            "fleet": {"num_vehicles": 2, "capacity": 4},
            "workday_start": "08:00",
            "workday_end": "18:00",
            "solver": {"solver_time_limit_s": 10, "allow_drop_visits": True},
        },
    )
    assert optimize_resp.status_code == 200
    body = optimize_resp.json()
    assert "plan_id" in body

    plan_id = body["plan_id"]
    plan_resp = client.get(f"/api/v1/plans/{plan_id}")
    assert plan_resp.status_code == 200
    assert plan_resp.json()["plan_id"] == plan_id

    csv_export = client.get(f"/api/v1/plans/{plan_id}/export", params={"format": "csv"})
    assert csv_export.status_code == 200
    assert "vehicle_idx" in csv_export.text

    pdf_export = client.get(f"/api/v1/plans/{plan_id}/export", params={"format": "pdf"})
    assert pdf_export.status_code == 200
    assert pdf_export.headers["content-type"].startswith("application/pdf")
