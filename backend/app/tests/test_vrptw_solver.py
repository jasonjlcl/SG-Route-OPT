from app.services.vrptw import solve_vrptw


def test_vrptw_synthetic_feasible():
    n = 7
    time_matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            time_matrix[i][j] = 300 + abs(i - j) * 60

    time_windows = [(8 * 3600, 18 * 3600)] * n
    service_times = [0] * n
    demands = [0, 1, 1, 1, 1, 1, 1]

    result = solve_vrptw(
        time_matrix=time_matrix,
        time_windows=time_windows,
        service_times_s=service_times,
        num_vehicles=2,
        depot_index=0,
        workday_window=(8 * 3600, 18 * 3600),
        demands=demands,
        vehicle_capacity=3,
        solver_time_limit_s=5,
    )

    assert result.feasible
    visited = set()
    for route in result.routes:
        for node in route:
            if node != 0:
                visited.add(node)
    assert visited == {1, 2, 3, 4, 5, 6}
