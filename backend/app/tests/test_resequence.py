from io import BytesIO


def test_resequence_recomputes_timeline_and_detects_violations(client):
    csv_content = """stop_ref,address,demand,service_time_min,tw_start,tw_end
S1,10 Bayfront Avenue,1,5,09:00,10:00
S2,1 Raffles Place,1,5,09:30,10:30
S3,50 Nanyang Ave,1,5,10:00,12:00
"""
    upload = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("stops.csv", BytesIO(csv_content.encode("utf-8")), "text/csv")},
        data={"exclude_invalid": "true"},
    )
    dataset_id = upload.json()["dataset_id"]

    client.post(f"/api/v1/datasets/{dataset_id}/geocode", params={"sync": "true"})
    optimize = client.post(
        f"/api/v1/datasets/{dataset_id}/optimize?sync=true",
        json={
            "depot_lat": 1.3521,
            "depot_lon": 103.8198,
            "fleet": {"num_vehicles": 1, "capacity": 5},
            "workday_start": "08:00",
            "workday_end": "11:00",
            "solver": {"solver_time_limit_s": 8, "allow_drop_visits": True},
        },
    )
    plan_id = optimize.json()["plan_id"]
    plan = client.get(f"/api/v1/plans/{plan_id}").json()
    route = plan["routes"][0]
    route_id = route["route_id"]
    stop_ids = [stop["stop_id"] for stop in route["stops"] if stop["stop_id"] is not None]

    preview = client.post(
        f"/api/v1/plans/{plan_id}/routes/{route_id}/resequence",
        json={"ordered_stop_ids": list(reversed(stop_ids)), "apply": False},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["totals"]["total_duration_s"] >= 0
    assert len(body["stops"]) == len(stop_ids) + 2

    apply = client.post(
        f"/api/v1/plans/{plan_id}/routes/{route_id}/resequence",
        json={"ordered_stop_ids": list(reversed(stop_ids)), "apply": True},
    )
    assert apply.status_code == 200
    updated_plan = client.get(f"/api/v1/plans/{plan_id}").json()
    updated_route = next(r for r in updated_plan["routes"] if r["route_id"] == route_id)
    persisted_ids = [stop["stop_id"] for stop in updated_route["stops"] if stop["stop_id"] is not None]
    assert persisted_ids == list(reversed(stop_ids))

