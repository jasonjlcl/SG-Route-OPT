from __future__ import annotations

from io import BytesIO

import pytest

from app.services.optimization import eta_recompute_with_time_windows
from app.services.traffic_provider_google import GoogleTrafficError, parse_google_routes_response
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
    dataset_id = upload.json()["dataset_id"]
    geocode = client.post(f"/api/v1/datasets/{dataset_id}/geocode", params={"sync": "true"})
    assert geocode.status_code == 200
    return int(dataset_id)


def test_parse_google_routes_response():
    payload = {
        "routes": [
            {
                "legs": [
                    {"duration": "120s", "staticDuration": "100s", "distanceMeters": 1100},
                    {"duration": "240s", "staticDuration": "200s", "distanceMeters": 2200},
                ],
                "polyline": {"encodedPolyline": "abc123"},
            }
        ]
    }

    parsed = parse_google_routes_response(payload, expected_legs=2)
    assert parsed.durations_s == [120, 240]
    assert parsed.static_durations_s == [100, 200]
    assert parsed.distances_m == [1100.0, 2200.0]
    assert parsed.polyline == "abc123"


def test_eta_recompute_with_time_windows():
    recomputed = eta_recompute_with_time_windows(
        route_nodes=[0, 1, 2, 0],
        route_start_s=8 * 3600,
        leg_travel_s=[600, 600, 600],
        time_windows=[(8 * 3600, 18 * 3600), (8 * 3600 + 1800, 12 * 3600), (9 * 3600, 15 * 3600)],
        service_times_s=[0, 300, 300],
    )

    assert recomputed["arrivals_s"] == [28800, 30600, 32400, 33300]
    assert recomputed["waiting_time_s"] == 2100
    assert recomputed["travel_time_s"] == 1800
    assert recomputed["service_time_s"] == 600
    assert recomputed["route_duration_s"] == 4500


def test_optimize_with_google_feature_uses_google_eta_source(client, monkeypatch):
    monkeypatch.setenv("FEATURE_GOOGLE_TRAFFIC", "true")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "unit-test-key")
    get_settings.cache_clear()

    class FakeGoogleProvider:
        enabled = True

        def get_segment_times(self, stops_ordered, departure_time_iso):
            return [180 for _ in range(max(0, len(stops_ordered) - 1))]

    monkeypatch.setattr("app.services.optimization.get_google_traffic_provider", lambda: FakeGoogleProvider())

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
            "use_live_traffic": True,
        },
    )
    assert optimize.status_code == 200

    plan_id = optimize.json()["plan_id"]
    plan = client.get(f"/api/v1/plans/{plan_id}")
    assert plan.status_code == 200
    body = plan.json()
    assert body["eta_source"] == "google_traffic"
    assert body["live_traffic_requested"] is True
    assert body["traffic_timestamp"] is not None


def test_fallback_logic_on_http_error(client, monkeypatch):
    monkeypatch.setenv("FEATURE_GOOGLE_TRAFFIC", "true")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "unit-test-key")
    get_settings.cache_clear()

    class FailingGoogleProvider:
        enabled = True

        def get_segment_times(self, stops_ordered, departure_time_iso):
            raise GoogleTrafficError(
                "Rate limited",
                code="GOOGLE_TRAFFIC_UNAVAILABLE",
                status_code=429,
            )

    monkeypatch.setattr("app.services.optimization.get_google_traffic_provider", lambda: FailingGoogleProvider())

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
            "use_live_traffic": True,
        },
    )
    assert optimize.status_code == 200
    result = optimize.json()
    assert result["eta_source"] in {"ml_baseline", "onemap"}
    assert result["live_traffic_requested"] is True
    assert result["warnings"]

    plan_id = result["plan_id"]
    plan = client.get(f"/api/v1/plans/{plan_id}")
    assert plan.status_code == 200
    body = plan.json()
    assert body["eta_source"] in {"ml_baseline", "onemap"}
    assert body["traffic_timestamp"] is None
    assert body["live_traffic_requested"] is True
