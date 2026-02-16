from app.services.optimization import calculate_route_duration_components


def test_duration_components_include_waiting_and_service():
    travel_matrix = [
        [0, 600, 600],
        [600, 0, 600],
        [600, 600, 0],
    ]
    service_times = [0, 300, 300]
    route_nodes = [0, 1, 2, 0]
    route_arrivals = [28800, 29400, 31000, 31900]

    metrics = calculate_route_duration_components(
        route_nodes=route_nodes,
        route_arrivals=route_arrivals,
        service_times_s=service_times,
        travel_time_matrix_s=travel_matrix,
    )

    assert metrics["travel_time_s"] == 1800
    assert metrics["service_time_s"] == 600
    assert metrics["waiting_time_s"] == 700
    assert metrics["route_duration_s"] == 3100
    assert metrics["route_duration_s"] == (
        metrics["travel_time_s"] + metrics["service_time_s"] + metrics["waiting_time_s"]
    )

