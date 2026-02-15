from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Dataset, Plan, Route, RouteStop, Stop
from app.services.ml_engine import get_ml_engine
from app.services.routing import get_routing_service
from app.services.vrptw import solve_vrptw
from app.utils.errors import AppError, log_error


@dataclass
class OptimizationPayload:
    depot_lat: float
    depot_lon: float
    num_vehicles: int
    capacity: int | None
    workday_start: str
    workday_end: str
    solver_time_limit_s: int
    allow_drop_visits: bool


def _hhmm_to_seconds(value: str) -> int:
    hh, mm = value.split(":")
    return int(hh) * 3600 + int(mm) * 60


def _seconds_to_iso(seconds_since_midnight: int) -> str:
    base = datetime.combine(date.today(), time.min)
    dt = base + timedelta(seconds=seconds_since_midnight)
    return dt.isoformat()


def _categorize_infeasibility(stops: list[Stop], payload: OptimizationPayload) -> tuple[str, list[str]]:
    if payload.capacity is not None and payload.capacity > 0:
        total_demand = sum(max(0, s.demand) for s in stops)
        if total_demand > payload.capacity * payload.num_vehicles:
            return (
                "capacity exceeded",
                ["add vehicles", "increase vehicle capacity", "reduce stops or demands"],
            )

    start = _hhmm_to_seconds(payload.workday_start)
    end = _hhmm_to_seconds(payload.workday_end)
    for stop in stops:
        if stop.tw_start and stop.tw_end:
            tw_s = _hhmm_to_seconds(stop.tw_start)
            tw_e = _hhmm_to_seconds(stop.tw_end)
            if tw_e < start or tw_s > end:
                return (
                    "time window conflict",
                    ["relax stop time windows", "extend workday", "add vehicles"],
                )

    return (
        "other constraint",
        ["add vehicles", "relax time windows", "reduce stops"],
    )


def optimize_dataset(db: Session, dataset_id: int, payload: OptimizationPayload) -> dict[str, Any]:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError(message=f"Dataset {dataset_id} not found", error_code="NOT_FOUND", status_code=404)

    stops = db.execute(
        select(Stop).where(Stop.dataset_id == dataset_id, Stop.geocode_status.in_(["SUCCESS", "MANUAL"]))
    ).scalars().all()

    if not stops:
        raise AppError(
            message="No geocoded stops available for optimization",
            error_code="NO_GEOCODED_STOPS",
            status_code=400,
            stage="OPTIMIZATION",
            dataset_id=dataset_id,
        )

    if payload.num_vehicles <= 0:
        raise AppError(
            message="num_vehicles must be > 0",
            error_code="VALIDATION_ERROR",
            status_code=400,
            stage="OPTIMIZATION",
            dataset_id=dataset_id,
        )

    if payload.capacity is not None and payload.capacity <= 0:
        raise AppError(
            message="capacity must be > 0 when provided",
            error_code="VALIDATION_ERROR",
            status_code=400,
            stage="OPTIMIZATION",
            dataset_id=dataset_id,
        )

    nodes: list[dict[str, Any]] = [{"kind": "depot", "lat": payload.depot_lat, "lon": payload.depot_lon, "stop": None}]
    for stop in stops:
        if stop.lat is None or stop.lon is None:
            continue
        nodes.append({"kind": "stop", "lat": stop.lat, "lon": stop.lon, "stop": stop})

    n = len(nodes)
    depart_bucket = payload.workday_start
    day_of_week = datetime.utcnow().weekday()
    depart_dt = datetime.combine(date.today(), datetime.strptime(payload.workday_start, "%H:%M").time())

    routing_service = get_routing_service()
    ml_engine = get_ml_engine()

    duration_matrix = [[0 for _ in range(n)] for _ in range(n)]
    distance_matrix = [[0.0 for _ in range(n)] for _ in range(n)]

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            o = nodes[i]
            d = nodes[j]
            try:
                base = routing_service.get_base_route(
                    db,
                    origin_lat=float(o["lat"]),
                    origin_lon=float(o["lon"]),
                    dest_lat=float(d["lat"]),
                    dest_lon=float(d["lon"]),
                    depart_bucket=depart_bucket,
                    day_of_week=day_of_week,
                )
                pred = ml_engine.predict_duration(
                    db,
                    od_cache_id=base.od_cache_id,
                    base_duration_s=base.duration_s,
                    distance_m=base.distance_m,
                    depart_dt=depart_dt,
                )
                duration_matrix[i][j] = max(1, int(round(pred.duration_s)))
                distance_matrix[i][j] = float(base.distance_m)
            except Exception as exc:  # noqa: BLE001
                log_error(
                    db,
                    "ROUTING",
                    str(exc),
                    dataset_id=dataset_id,
                    details={"from": i, "to": j},
                )
                raise AppError(
                    message="Failed while building OD matrix",
                    error_code="ROUTING_ERROR",
                    status_code=502,
                    stage="ROUTING",
                    dataset_id=dataset_id,
                    details={"from": i, "to": j},
                ) from exc

    workday_window = (_hhmm_to_seconds(payload.workday_start), _hhmm_to_seconds(payload.workday_end))
    time_windows: list[tuple[int, int]] = [workday_window]
    service_times = [0]
    demands = [0]

    for node in nodes[1:]:
        stop = node["stop"]
        if stop.tw_start and stop.tw_end:
            time_windows.append((_hhmm_to_seconds(stop.tw_start), _hhmm_to_seconds(stop.tw_end)))
        else:
            time_windows.append(workday_window)
        service_times.append(int(stop.service_time_min or 0) * 60)
        demands.append(int(stop.demand or 0))

    if payload.capacity is not None:
        total_demand = sum(demands)
        if total_demand > payload.capacity * payload.num_vehicles:
            reason, suggestions = _categorize_infeasibility(stops, payload)
            plan = Plan(
                dataset_id=dataset_id,
                depot_lat=payload.depot_lat,
                depot_lon=payload.depot_lon,
                num_vehicles=payload.num_vehicles,
                status="INFEASIBLE",
                infeasibility_reason=reason,
            )
            db.add(plan)
            db.commit()
            db.refresh(plan)
            return {
                "plan_id": plan.id,
                "feasible": False,
                "infeasibility_reason": reason,
                "suggestions": suggestions,
            }

    result = solve_vrptw(
        time_matrix=duration_matrix,
        time_windows=time_windows,
        service_times_s=service_times,
        num_vehicles=payload.num_vehicles,
        depot_index=0,
        workday_window=workday_window,
        demands=demands if payload.capacity is not None else None,
        vehicle_capacity=payload.capacity,
        solver_time_limit_s=payload.solver_time_limit_s,
        allow_drop_visits=payload.allow_drop_visits,
    )

    if not result.feasible:
        reason, suggestions = _categorize_infeasibility(stops, payload)
        plan = Plan(
            dataset_id=dataset_id,
            depot_lat=payload.depot_lat,
            depot_lon=payload.depot_lon,
            num_vehicles=payload.num_vehicles,
            status="INFEASIBLE",
            infeasibility_reason=reason,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        return {
            "plan_id": plan.id,
            "feasible": False,
            "infeasibility_reason": reason,
            "suggestions": suggestions,
        }

    plan_status = "SUCCESS" if not result.unserved_nodes else "PARTIAL"
    plan = Plan(
        dataset_id=dataset_id,
        depot_lat=payload.depot_lat,
        depot_lon=payload.depot_lon,
        num_vehicles=payload.num_vehicles,
        status=plan_status,
        objective_value=float(result.objective),
    )
    db.add(plan)
    db.flush()

    route_summaries = []
    for vehicle_idx, route_nodes in enumerate(result.routes):
        total_distance = 0.0
        total_duration = 0.0
        for a, b in zip(route_nodes[:-1], route_nodes[1:]):
            total_distance += distance_matrix[a][b]
            total_duration += duration_matrix[a][b]

        route_row = Route(
            plan_id=plan.id,
            vehicle_idx=vehicle_idx,
            total_distance_m=total_distance,
            total_duration_s=total_duration,
        )
        db.add(route_row)
        db.flush()

        for seq, node_idx in enumerate(route_nodes):
            node = nodes[node_idx]
            stop = node["stop"]
            arrival_s = int(result.arrivals[vehicle_idx][seq])
            service_start_s = arrival_s
            service_end_s = arrival_s + (service_times[node_idx] if node_idx < len(service_times) else 0)
            tw_s, tw_e = time_windows[node_idx]
            db.add(
                RouteStop(
                    route_id=route_row.id,
                    sequence_idx=seq,
                    stop_id=stop.id if stop else None,
                    eta_iso=_seconds_to_iso(arrival_s),
                    arrival_window_start_iso=_seconds_to_iso(tw_s),
                    arrival_window_end_iso=_seconds_to_iso(tw_e),
                    service_start_iso=_seconds_to_iso(service_start_s),
                    service_end_iso=_seconds_to_iso(service_end_s),
                )
            )

        route_summaries.append(
            {
                "vehicle_idx": vehicle_idx,
                "total_distance_m": round(total_distance, 2),
                "total_duration_s": int(total_duration),
                "stop_count": max(0, len(route_nodes) - 2),
            }
        )

    dataset.status = "OPTIMIZED"
    db.commit()
    db.refresh(plan)

    unserved_stop_ids = [nodes[idx]["stop"].id for idx in result.unserved_nodes if nodes[idx]["stop"]]

    return {
        "plan_id": plan.id,
        "feasible": True,
        "status": plan.status,
        "objective_value": float(plan.objective_value or 0),
        "route_summary": route_summaries,
        "unserved_stop_ids": unserved_stop_ids,
    }


def get_plan_details(db: Session, plan_id: int) -> dict[str, Any]:
    plan = db.execute(
        select(Plan)
        .where(Plan.id == plan_id)
        .options(joinedload(Plan.routes).joinedload(Route.route_stops).joinedload(RouteStop.stop), joinedload(Plan.dataset))
    ).unique().scalar_one_or_none()

    if plan is None:
        raise AppError(message=f"Plan {plan_id} not found", error_code="NOT_FOUND", status_code=404)

    routes_payload = []
    served_stop_ids = set()

    for route in sorted(plan.routes, key=lambda r: r.vehicle_idx):
        stops_payload = []
        for route_stop in sorted(route.route_stops, key=lambda x: x.sequence_idx):
            stop = route_stop.stop
            if stop is not None:
                served_stop_ids.add(stop.id)
            stops_payload.append(
                {
                    "sequence_idx": route_stop.sequence_idx,
                    "stop_id": stop.id if stop else None,
                    "stop_ref": stop.stop_ref if stop else "DEPOT",
                    "address": stop.address if stop else "DEPOT",
                    "lat": stop.lat if stop else plan.depot_lat,
                    "lon": stop.lon if stop else plan.depot_lon,
                    "eta_iso": route_stop.eta_iso,
                    "arrival_window_start_iso": route_stop.arrival_window_start_iso,
                    "arrival_window_end_iso": route_stop.arrival_window_end_iso,
                    "service_start_iso": route_stop.service_start_iso,
                    "service_end_iso": route_stop.service_end_iso,
                }
            )

        routes_payload.append(
            {
                "route_id": route.id,
                "vehicle_idx": route.vehicle_idx,
                "total_distance_m": route.total_distance_m,
                "total_duration_s": route.total_duration_s,
                "stops": stops_payload,
            }
        )

    all_stops = db.execute(select(Stop).where(Stop.dataset_id == plan.dataset_id)).scalars().all()
    unserved = [
        {
            "stop_id": s.id,
            "stop_ref": s.stop_ref,
            "address": s.address,
        }
        for s in all_stops
        if s.id not in served_stop_ids and s.geocode_status in {"SUCCESS", "MANUAL"}
    ]

    return {
        "plan_id": plan.id,
        "dataset_id": plan.dataset_id,
        "status": plan.status,
        "objective_value": float(plan.objective_value or 0),
        "infeasibility_reason": plan.infeasibility_reason,
        "depot": {"lat": plan.depot_lat, "lon": plan.depot_lon},
        "routes": routes_payload,
        "unserved_stops": unserved,
    }
