from __future__ import annotations

from dataclasses import dataclass

from ortools.constraint_solver import pywrapcp, routing_enums_pb2


@dataclass
class SolverResult:
    feasible: bool
    routes: list[list[int]]
    arrivals: list[list[int]]
    objective: int
    unserved_nodes: list[int]


def solve_vrptw(
    *,
    time_matrix: list[list[int]],
    time_windows: list[tuple[int, int]],
    service_times_s: list[int],
    num_vehicles: int,
    depot_index: int,
    workday_window: tuple[int, int],
    demands: list[int] | None = None,
    vehicle_capacity: int | None = None,
    solver_time_limit_s: int = 15,
    allow_drop_visits: bool = False,
    drop_penalty: int = 100000,
) -> SolverResult:
    n = len(time_matrix)
    manager = pywrapcp.RoutingIndexManager(n, num_vehicles, depot_index)
    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(time_matrix[from_node][to_node]) + int(service_times_s[from_node])

    transit_idx = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    routing.AddDimension(
        transit_idx,
        12 * 3600,
        24 * 3600,
        False,
        "Time",
    )
    time_dim = routing.GetDimensionOrDie("Time")

    for node in range(n):
        idx = manager.NodeToIndex(node)
        start, end = time_windows[node]
        time_dim.CumulVar(idx).SetRange(int(start), int(end))

    for vehicle in range(num_vehicles):
        start_idx = routing.Start(vehicle)
        end_idx = routing.End(vehicle)
        time_dim.CumulVar(start_idx).SetRange(int(workday_window[0]), int(workday_window[1]))
        time_dim.CumulVar(end_idx).SetRange(int(workday_window[0]), int(workday_window[1]))

    if demands is not None and vehicle_capacity is not None:
        def demand_callback(from_index: int) -> int:
            node = manager.IndexToNode(from_index)
            return int(demands[node])

        demand_idx = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            demand_idx,
            0,
            [int(vehicle_capacity)] * num_vehicles,
            True,
            "Capacity",
        )

    if allow_drop_visits:
        for node in range(n):
            if node == depot_index:
                continue
            routing.AddDisjunction([manager.NodeToIndex(node)], drop_penalty)

    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.FromSeconds(int(solver_time_limit_s))

    solution = routing.SolveWithParameters(search_params)
    if solution is None:
        return SolverResult(feasible=False, routes=[], arrivals=[], objective=0, unserved_nodes=[])

    routes: list[list[int]] = []
    arrivals: list[list[int]] = []

    visited = set()
    for vehicle in range(num_vehicles):
        idx = routing.Start(vehicle)
        route_nodes: list[int] = []
        route_arrivals: list[int] = []
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            route_nodes.append(node)
            route_arrivals.append(solution.Value(time_dim.CumulVar(idx)))
            visited.add(node)
            idx = solution.Value(routing.NextVar(idx))

        end_node = manager.IndexToNode(idx)
        route_nodes.append(end_node)
        route_arrivals.append(solution.Value(time_dim.CumulVar(idx)))
        visited.add(end_node)

        routes.append(route_nodes)
        arrivals.append(route_arrivals)

    unserved = [node for node in range(n) if node not in visited and node != depot_index]

    return SolverResult(
        feasible=True,
        routes=routes,
        arrivals=arrivals,
        objective=int(solution.ObjectiveValue()),
        unserved_nodes=unserved,
    )
