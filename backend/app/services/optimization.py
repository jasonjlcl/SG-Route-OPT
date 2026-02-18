from __future__ import annotations

from dataclasses import dataclass
import json
from datetime import date, datetime, time, timedelta, timezone
import logging
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.models import Dataset, Plan, Route, RouteStop, Stop
from app.providers.google_routes import GoogleRouteLeg
from app.services.ml_engine import get_ml_engine
from app.services.ml_uplift import get_ml_uplift_service
from app.services.routing import get_routing_service
from app.services.traffic_provider_google import GoogleTrafficError, get_google_traffic_provider
from app.services.vrptw import solve_vrptw
from app.utils.errors import AppError, log_error
from app.utils.settings import get_settings


MATRIX_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "matrix"
MATRIX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOGGER = logging.getLogger(__name__)

ETA_SOURCE_GOOGLE_TRAFFIC = "google_traffic"
ETA_SOURCE_ML_UPLIFT = "ml_uplift"
ETA_SOURCE_ML_BASELINE = "ml_baseline"
ETA_SOURCE_ONEMAP = "onemap"
SG_TZ = timezone(timedelta(hours=8))
MIN_GOOGLE_DEPARTURE_LEAD_SECONDS = 120


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
    use_live_traffic: bool = False


def _ensure_wgs84(lat: float, lon: float) -> tuple[float, float]:
    lat_value = float(lat)
    lon_value = float(lon)
    if not (-90 <= lat_value <= 90 and -180 <= lon_value <= 180):
        raise AppError(
            message="Invalid WGS84 coordinate range",
            error_code="INVALID_COORDINATE",
            status_code=400,
            stage="OPTIMIZATION",
            details={"lat": lat_value, "lon": lon_value},
        )
    return lat_value, lon_value


def _hhmm_to_seconds(value: str) -> int:
    hh, mm = value.split(":")
    return int(hh) * 3600 + int(mm) * 60


def _seconds_to_iso(seconds_since_midnight: int) -> str:
    base = datetime.combine(date.today(), time.min)
    dt = base + timedelta(seconds=seconds_since_midnight)
    return dt.isoformat()


def _ensure_future_google_departure(depart_dt: datetime) -> datetime:
    candidate = depart_dt if depart_dt.tzinfo else depart_dt.replace(tzinfo=SG_TZ)
    now_sg = datetime.now(SG_TZ) + timedelta(seconds=MIN_GOOGLE_DEPARTURE_LEAD_SECONDS)
    if candidate < now_sg:
        return now_sg
    return candidate


def _eta_source_from_artifact(artifact: dict[str, Any]) -> str:
    matrix_strategy = str(artifact.get("matrix_strategy") or "").lower()
    if matrix_strategy == ETA_SOURCE_ML_UPLIFT:
        return ETA_SOURCE_ML_UPLIFT
    version = str(artifact.get("chosen_model_version") or "")
    if version in {"", "fallback_v1"}:
        return ETA_SOURCE_ONEMAP
    return ETA_SOURCE_ML_BASELINE


def _google_error_details_json(exc: GoogleTrafficError) -> str:
    details = getattr(exc, "details", None)
    if not details:
        return "{}"
    try:
        return json.dumps(details, ensure_ascii=True, default=str)
    except Exception:  # noqa: BLE001
        return str(details)


def eta_recompute_with_time_windows(
    *,
    route_nodes: list[int],
    route_start_s: int,
    leg_travel_s: list[int],
    time_windows: list[tuple[int, int]],
    service_times_s: list[int],
) -> dict[str, Any]:
    if len(route_nodes) < 2:
        return {
            "arrivals_s": [int(route_start_s)] if route_nodes else [],
            "service_start_s": [int(route_start_s)] if route_nodes else [],
            "service_end_s": [int(route_start_s)] if route_nodes else [],
            "travel_time_s": 0,
            "waiting_time_s": 0,
            "service_time_s": 0,
            "route_duration_s": 0,
            "route_end_s": int(route_start_s),
        }
    if len(leg_travel_s) != len(route_nodes) - 1:
        raise ValueError("leg_travel_s must have exactly len(route_nodes)-1 entries")

    arrivals_s: list[int] = [int(route_start_s)]
    service_start_s: list[int] = [int(route_start_s)]
    service_end_s: list[int] = [int(route_start_s)]
    current_depart_s = int(route_start_s)
    travel_time_s = 0
    waiting_time_s = 0
    service_time_s = 0

    for seq in range(1, len(route_nodes)):
        node_idx = int(route_nodes[seq])
        leg = max(0, int(leg_travel_s[seq - 1]))
        travel_time_s += leg
        raw_arrival_s = current_depart_s + leg

        if node_idx == 0:
            eta_s = raw_arrival_s
            svc_start_s = eta_s
            svc_end_s = eta_s
            current_depart_s = eta_s
        else:
            tw_start_s, _ = time_windows[node_idx] if node_idx < len(time_windows) else (0, 24 * 3600)
            svc_s = int(service_times_s[node_idx]) if node_idx < len(service_times_s) else 0
            eta_s = max(raw_arrival_s, int(tw_start_s))
            waiting_time_s += max(0, eta_s - raw_arrival_s)
            svc_start_s = eta_s
            svc_end_s = svc_start_s + svc_s
            service_time_s += svc_s
            current_depart_s = svc_end_s

        arrivals_s.append(int(eta_s))
        service_start_s.append(int(svc_start_s))
        service_end_s.append(int(svc_end_s))

    route_duration_s = max(0, int(current_depart_s - route_start_s))
    return {
        "arrivals_s": arrivals_s,
        "service_start_s": service_start_s,
        "service_end_s": service_end_s,
        "travel_time_s": int(travel_time_s),
        "waiting_time_s": int(waiting_time_s),
        "service_time_s": int(service_time_s),
        "route_duration_s": int(route_duration_s),
        "route_end_s": int(current_depart_s),
    }


def _collect_route_points(
    *,
    route_nodes: list[int],
    nodes: list[dict[str, Any]],
    depot_lat: float,
    depot_lon: float,
) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    for node_idx in route_nodes:
        node_idx_int = int(node_idx)
        if node_idx_int == 0:
            points.append({"lat": float(depot_lat), "lon": float(depot_lon)})
            continue
        if node_idx_int < 0 or node_idx_int >= len(nodes):
            raise AppError(
                message="Route node index out of range",
                error_code="MATRIX_ARTIFACT_INVALID",
                status_code=400,
                stage="OPTIMIZATION",
                details={"node_idx": node_idx_int},
            )
        node = nodes[node_idx_int]
        points.append({"lat": float(node["lat"]), "lon": float(node["lon"])})
    return points


def _google_route_legs(
    *,
    provider: Any,
    route_points: list[dict[str, float]],
    departure_time_iso: str,
    routing_preference: str,
) -> list[GoogleRouteLeg]:
    if hasattr(provider, "compute_routes"):
        legs = provider.compute_routes(
            route_points,
            departure_time_iso,
            routing_preference=routing_preference,
            include_polyline=True,
        )
        return [GoogleRouteLeg(distance_m=float(leg.distance_m), duration_s=int(leg.duration_s), static_duration_s=int(leg.static_duration_s)) for leg in legs]

    leg_times = provider.get_segment_times(route_points, departure_time_iso)
    return [GoogleRouteLeg(distance_m=0.0, duration_s=max(1, int(v)), static_duration_s=max(1, int(v))) for v in leg_times]


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


def calculate_route_duration_components(
    *,
    route_nodes: list[int],
    route_arrivals: list[int],
    service_times_s: list[int],
    travel_time_matrix_s: list[list[int]],
) -> dict[str, int]:
    if len(route_nodes) != len(route_arrivals):
        raise ValueError("route_nodes and route_arrivals must be aligned")

    if not route_nodes:
        return {
            "route_start_s": 0,
            "route_end_s": 0,
            "route_duration_s": 0,
            "travel_time_s": 0,
            "service_time_s": 0,
            "waiting_time_s": 0,
        }

    travel_time_s = 0
    service_time_s = 0
    waiting_time_s = 0

    for seq in range(1, len(route_nodes)):
        prev = route_nodes[seq - 1]
        current = route_nodes[seq]
        leg_travel = int(travel_time_matrix_s[prev][current])
        prev_service = int(service_times_s[prev]) if prev < len(service_times_s) else 0
        expected_without_wait = int(route_arrivals[seq - 1]) + prev_service + leg_travel
        leg_wait = max(0, int(route_arrivals[seq]) - expected_without_wait)

        travel_time_s += leg_travel
        service_time_s += prev_service
        waiting_time_s += leg_wait

    route_start_s = int(route_arrivals[0])
    route_end_s = int(route_arrivals[-1])
    route_duration_s = max(0, route_end_s - route_start_s)

    return {
        "route_start_s": route_start_s,
        "route_end_s": route_end_s,
        "route_duration_s": route_duration_s,
        "travel_time_s": travel_time_s,
        "service_time_s": service_time_s,
        "waiting_time_s": waiting_time_s,
    }


def save_matrix_artifact(*, dataset_id: int, job_id: str, artifact: dict[str, Any]) -> str:
    target = MATRIX_CACHE_DIR / f"dataset_{dataset_id}_{job_id}.json"
    target.write_text(json.dumps(artifact), encoding="utf-8")
    return str(target)


def load_matrix_artifact(path: str) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        raise AppError(
            message="Matrix artifact not found",
            error_code="MATRIX_ARTIFACT_NOT_FOUND",
            status_code=404,
            stage="ROUTING",
            details={"path": path},
        )
    return json.loads(target.read_text(encoding="utf-8"))


def build_optimization_matrix_artifact(
    db: Session,
    *,
    dataset_id: int,
    payload: OptimizationPayload,
    progress_cb: Callable[[int, str], None] | None = None,
    force_model_version: str | None = None,
    force_uplift: bool | None = None,
) -> dict[str, Any]:
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

    depot_lat, depot_lon = _ensure_wgs84(payload.depot_lat, payload.depot_lon)
    nodes: list[dict[str, Any]] = [{"kind": "depot", "lat": depot_lat, "lon": depot_lon, "stop": None}]
    for stop in stops:
        if stop.lat is None or stop.lon is None:
            continue
        stop_lat, stop_lon = _ensure_wgs84(stop.lat, stop.lon)
        nodes.append({"kind": "stop", "lat": stop_lat, "lon": stop_lon, "stop": stop})

    if len(nodes) <= 1:
        raise AppError(
            message="No geocoded stops available for matrix build",
            error_code="NO_GEOCODED_STOPS",
            status_code=400,
            stage="ROUTING",
            dataset_id=dataset_id,
        )

    if progress_cb:
        progress_cb(5, "Preparing optimization nodes")

    n = len(nodes)
    depart_bucket = payload.workday_start
    day_of_week = datetime.utcnow().weekday()
    depart_dt = datetime.combine(date.today(), datetime.strptime(payload.workday_start, "%H:%M").time())

    routing_service = get_routing_service()
    ml_engine = get_ml_engine()
    uplift_service = get_ml_uplift_service()
    settings = get_settings()

    duration_matrix = [[0 for _ in range(n)] for _ in range(n)]
    base_duration_matrix = [[0.0 for _ in range(n)] for _ in range(n)]
    distance_matrix = [[0.0 for _ in range(n)] for _ in range(n)]
    uplift_factor_matrix = [[1.0 for _ in range(n)] for _ in range(n)]
    pair_total = max(1, n * n - n)
    pair_done = 0
    selected_versions: list[str] = []
    uplift_feature_rows: list[dict[str, Any]] = []
    uplift_pairs: list[tuple[int, int]] = []
    uplift_requested = bool(settings.feature_ml_uplift if force_uplift is None else force_uplift)
    uplift_available = bool(uplift_requested and uplift_service.model_available())
    uplift_model_version = uplift_service.model_version if uplift_available else None
    if uplift_requested and not uplift_available:
        LOGGER.info("ML uplift flag enabled but model artifact not found; falling back to baseline matrix.")

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
                    origin_lat=float(o["lat"]),
                    origin_lon=float(o["lon"]),
                    dest_lat=float(d["lat"]),
                    dest_lon=float(d["lon"]),
                    force_model_version=force_model_version,
                )
                duration_matrix[i][j] = max(1, int(round(pred.duration_s)))
                base_duration_matrix[i][j] = float(base.duration_s)
                distance_matrix[i][j] = float(base.distance_m)
                selected_versions.append(pred.model_version)
                if uplift_available:
                    uplift_feature_rows.append(
                        uplift_service.build_inference_row(
                            origin_lat=float(o["lat"]),
                            origin_lng=float(o["lon"]),
                            dest_lat=float(d["lat"]),
                            dest_lng=float(d["lon"]),
                            distance_m=float(base.distance_m),
                            departure_time_iso=depart_dt.isoformat(),
                            static_duration_s=float(base.duration_s),
                        )
                    )
                    uplift_pairs.append((i, j))
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
            pair_done += 1
            if progress_cb and (pair_done % max(1, pair_total // 20) == 0 or pair_done == pair_total):
                progress = 10 + int((pair_done / pair_total) * 60)
                progress_cb(progress, f"Building OD matrix {pair_done}/{pair_total}")

    uplift_applied = False
    if uplift_available and uplift_feature_rows:
        factors = uplift_service.predict_factors(uplift_feature_rows)
        if factors is not None and len(factors) == len(uplift_pairs):
            for idx, (i, j) in enumerate(uplift_pairs):
                factor = float(factors[idx])
                uplift_factor_matrix[i][j] = factor
                duration_matrix[i][j] = max(1, int(round(float(duration_matrix[i][j]) * factor)))
            uplift_applied = True
        else:
            LOGGER.warning("ML uplift prediction unavailable; keeping baseline duration matrix.")

    workday_window = (_hhmm_to_seconds(payload.workday_start), _hhmm_to_seconds(payload.workday_end))
    time_windows: list[tuple[int, int]] = [workday_window]
    service_times = [0]
    demands = [0]

    serializable_nodes: list[dict[str, Any]] = [
        {
            "node_idx": 0,
            "kind": "depot",
            "stop_id": None,
            "stop_ref": "DEPOT",
            "lat": depot_lat,
            "lon": depot_lon,
            "demand": 0,
            "service_time_min": 0,
            "tw_start": payload.workday_start,
            "tw_end": payload.workday_end,
        }
    ]

    for idx, node in enumerate(nodes[1:], start=1):
        stop = node["stop"]
        if stop.tw_start and stop.tw_end:
            tw_pair = (_hhmm_to_seconds(stop.tw_start), _hhmm_to_seconds(stop.tw_end))
        else:
            tw_pair = workday_window
        time_windows.append(tw_pair)
        service_times.append(int(stop.service_time_min or 0) * 60)
        demands.append(int(stop.demand or 0))
        serializable_nodes.append(
            {
                "node_idx": idx,
                "kind": "stop",
                "stop_id": stop.id,
                "stop_ref": stop.stop_ref,
                "lat": float(node["lat"]),
                "lon": float(node["lon"]),
                "demand": int(stop.demand or 0),
                "service_time_min": int(stop.service_time_min or 0),
                "tw_start": stop.tw_start,
                "tw_end": stop.tw_end,
            }
        )

    model_version_counts: dict[str, int] = {}
    for version in selected_versions:
        model_version_counts[version] = model_version_counts.get(version, 0) + 1
    chosen_version = max(model_version_counts.items(), key=lambda item: item[1])[0] if model_version_counts else "fallback_v1"
    if uplift_applied:
        matrix_strategy = ETA_SOURCE_ML_UPLIFT
    elif chosen_version in {"", "fallback_v1"}:
        matrix_strategy = ETA_SOURCE_ONEMAP
    else:
        matrix_strategy = ETA_SOURCE_ML_BASELINE

    return {
        "dataset_id": dataset_id,
        "generated_at": datetime.utcnow().isoformat(),
        "depot": {"lat": depot_lat, "lon": depot_lon},
        "workday_start": payload.workday_start,
        "workday_end": payload.workday_end,
        "num_vehicles": payload.num_vehicles,
        "capacity": payload.capacity,
        "allow_drop_visits": payload.allow_drop_visits,
        "solver_time_limit_s": payload.solver_time_limit_s,
        "workday_window": [workday_window[0], workday_window[1]],
        "nodes": serializable_nodes,
        "time_windows": [[start, end] for start, end in time_windows],
        "service_times_s": service_times,
        "demands": demands,
        "duration_matrix_s": duration_matrix,
        "base_duration_matrix_s": base_duration_matrix,
        "distance_matrix_m": distance_matrix,
        "depart_bucket": depart_bucket,
        "day_of_week": day_of_week,
        "chosen_model_version": chosen_version,
        "model_version_counts": model_version_counts,
        "matrix_strategy": matrix_strategy,
        "uplift_applied": bool(uplift_applied),
        "uplift_model_version": uplift_model_version,
        "uplift_factor_matrix": uplift_factor_matrix if uplift_applied else None,
    }


def optimize_dataset(
    db: Session,
    dataset_id: int,
    payload: OptimizationPayload,
    *,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
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

    artifact = build_optimization_matrix_artifact(
        db,
        dataset_id=dataset_id,
        payload=payload,
        progress_cb=progress_cb,
    )
    return solve_optimization_from_artifact(
        db,
        dataset_id=dataset_id,
        payload=payload,
        artifact=artifact,
        progress_cb=progress_cb,
    )


def solve_optimization_from_artifact(
    db: Session,
    *,
    dataset_id: int,
    payload: OptimizationPayload,
    artifact: dict[str, Any],
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError(message=f"Dataset {dataset_id} not found", error_code="NOT_FOUND", status_code=404)

    nodes = artifact.get("nodes", [])
    if not nodes or len(nodes) <= 1:
        raise AppError(
            message="Optimization artifact has no route nodes",
            error_code="MATRIX_ARTIFACT_INVALID",
            status_code=400,
            stage="OPTIMIZATION",
        )

    duration_matrix = artifact.get("duration_matrix_s", [])
    distance_matrix = artifact.get("distance_matrix_m", [])
    time_windows = [tuple(map(int, pair)) for pair in artifact.get("time_windows", [])]
    service_times = [int(v) for v in artifact.get("service_times_s", [])]
    demands = [int(v) for v in artifact.get("demands", [])]
    workday_window_raw = artifact.get("workday_window", [_hhmm_to_seconds(payload.workday_start), _hhmm_to_seconds(payload.workday_end)])
    workday_window = (int(workday_window_raw[0]), int(workday_window_raw[1]))

    stop_ids = [int(node["stop_id"]) for node in nodes if node.get("stop_id") is not None]
    stop_rows = db.execute(select(Stop).where(Stop.id.in_(stop_ids))).scalars().all() if stop_ids else []
    stop_by_id = {stop.id: stop for stop in stop_rows}
    ordered_stops = [stop_by_id[node["stop_id"]] for node in nodes if node.get("stop_id") in stop_by_id]

    if payload.capacity is not None:
        total_demand = sum(demands)
        if total_demand > payload.capacity * payload.num_vehicles:
            reason, suggestions = _categorize_infeasibility(ordered_stops, payload)
            plan = Plan(
                dataset_id=dataset_id,
                depot_lat=float(artifact["depot"]["lat"]),
                depot_lon=float(artifact["depot"]["lon"]),
                num_vehicles=payload.num_vehicles,
                vehicle_capacity=payload.capacity,
                workday_start=payload.workday_start,
                workday_end=payload.workday_end,
                status="INFEASIBLE",
                infeasibility_reason=reason,
                eta_source=_eta_source_from_artifact(artifact),
                live_traffic_requested=bool(payload.use_live_traffic),
            )
            db.add(plan)
            dataset.status = "OPTIMIZATION_FAILED"
            db.commit()
            db.refresh(plan)
            if progress_cb:
                progress_cb(100, "Optimization infeasible: capacity exceeded")
            return {
                "plan_id": plan.id,
                "feasible": False,
                "infeasibility_reason": reason,
                "suggestions": suggestions,
                "eta_source": plan.eta_source,
                "traffic_timestamp": plan.traffic_timestamp_iso,
                "live_traffic_requested": bool(payload.use_live_traffic),
            }

    if progress_cb:
        progress_cb(80, "Solving VRPTW")
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
        reason, suggestions = _categorize_infeasibility(ordered_stops, payload)
        plan = Plan(
            dataset_id=dataset_id,
            depot_lat=float(artifact["depot"]["lat"]),
            depot_lon=float(artifact["depot"]["lon"]),
            num_vehicles=payload.num_vehicles,
            vehicle_capacity=payload.capacity,
            workday_start=payload.workday_start,
            workday_end=payload.workday_end,
            status="INFEASIBLE",
            infeasibility_reason=reason,
            eta_source=_eta_source_from_artifact(artifact),
            live_traffic_requested=bool(payload.use_live_traffic),
        )
        db.add(plan)
        dataset.status = "OPTIMIZATION_FAILED"
        db.commit()
        db.refresh(plan)
        if progress_cb:
            progress_cb(100, f"Optimization infeasible: {reason}")
        return {
            "plan_id": plan.id,
            "feasible": False,
            "infeasibility_reason": reason,
            "suggestions": suggestions,
            "eta_source": plan.eta_source,
            "traffic_timestamp": plan.traffic_timestamp_iso,
            "live_traffic_requested": bool(payload.use_live_traffic),
        }

    plan_status = "SUCCESS" if not result.unserved_nodes else "PARTIAL"
    eta_source = _eta_source_from_artifact(artifact)
    traffic_timestamp: str | None = None
    warnings: list[str] = []
    plan = Plan(
        dataset_id=dataset_id,
        depot_lat=float(artifact["depot"]["lat"]),
        depot_lon=float(artifact["depot"]["lon"]),
        num_vehicles=payload.num_vehicles,
        vehicle_capacity=payload.capacity,
        workday_start=payload.workday_start,
        workday_end=payload.workday_end,
        status=plan_status,
        objective_value=float(result.objective),
        eta_source=eta_source,
        live_traffic_requested=bool(payload.use_live_traffic),
    )
    db.add(plan)
    db.flush()

    route_records: list[dict[str, Any]] = []
    for vehicle_idx, route_nodes in enumerate(result.routes):
        total_distance = 0.0
        for a, b in zip(route_nodes[:-1], route_nodes[1:]):
            total_distance += float(distance_matrix[a][b])

        arrivals_s = [int(v) for v in result.arrivals[vehicle_idx]]
        duration_components = calculate_route_duration_components(
            route_nodes=route_nodes,
            route_arrivals=arrivals_s,
            service_times_s=service_times,
            travel_time_matrix_s=duration_matrix,
        )
        service_start_s: list[int] = []
        service_end_s: list[int] = []
        for seq, node_idx in enumerate(route_nodes):
            arrival_s = arrivals_s[seq]
            service_s = int(service_times[node_idx]) if node_idx < len(service_times) else 0
            if int(node_idx) == 0:
                service_start_s.append(int(arrival_s))
                service_end_s.append(int(arrival_s))
            else:
                service_start_s.append(int(arrival_s))
                service_end_s.append(int(arrival_s + service_s))

        route_records.append(
            {
                "vehicle_idx": vehicle_idx,
                "route_nodes": [int(v) for v in route_nodes],
                "arrivals_s": arrivals_s,
                "service_start_s": service_start_s,
                "service_end_s": service_end_s,
                "total_distance_m": float(total_distance),
                "components": {
                    "route_start_s": int(duration_components["route_start_s"]),
                    "route_end_s": int(duration_components["route_end_s"]),
                    "route_duration_s": int(duration_components["route_duration_s"]),
                    "travel_time_s": int(duration_components["travel_time_s"]),
                    "service_time_s": int(duration_components["service_time_s"]),
                    "waiting_time_s": int(duration_components["waiting_time_s"]),
                },
            }
        )

    settings = get_settings()
    uplift_service = get_ml_uplift_service()
    google_requested = bool(settings.feature_google_traffic and payload.use_live_traffic)
    if payload.use_live_traffic and not settings.feature_google_traffic:
        warnings.append("Google traffic feature flag disabled; using baseline ETAs.")
    if google_requested:
        if progress_cb:
            progress_cb(90, "Fetching traffic-aware ETAs (Google) ...")
        try:
            provider = get_google_traffic_provider()
            if not provider.enabled:
                raise GoogleTrafficError("Google traffic is not configured", code="GOOGLE_TRAFFIC_DISABLED")

            recomputed_records: list[dict[str, Any]] = []
            collected_uplift_rows = 0
            for record in route_records:
                route_nodes = [int(v) for v in record["route_nodes"]]
                if len(route_nodes) < 2:
                    recomputed_records.append(record)
                    continue

                route_start_s = int(record["components"]["route_start_s"])
                depart_dt = _ensure_future_google_departure(
                    datetime.combine(date.today(), time.min) + timedelta(seconds=route_start_s)
                )
                if traffic_timestamp is None:
                    traffic_timestamp = depart_dt.isoformat()

                route_points = _collect_route_points(
                    route_nodes=route_nodes,
                    nodes=nodes,
                    depot_lat=float(artifact["depot"]["lat"]),
                    depot_lon=float(artifact["depot"]["lon"]),
                )
                google_legs = _google_route_legs(
                    provider=provider,
                    route_points=route_points,
                    departure_time_iso=depart_dt.isoformat(),
                    routing_preference=settings.resolved_google_routing_preference,
                )
                leg_travel_s = [max(1, int(leg.duration_s)) for leg in google_legs]
                recomputed = eta_recompute_with_time_windows(
                    route_nodes=route_nodes,
                    route_start_s=route_start_s,
                    leg_travel_s=leg_travel_s,
                    time_windows=time_windows,
                    service_times_s=service_times,
                )
                leg_departure_isos = [_seconds_to_iso(int(recomputed["service_end_s"][idx])) for idx in range(len(route_nodes) - 1)]
                collected_uplift_rows += uplift_service.collect_google_leg_samples(
                    route_points=route_points,
                    leg_departure_isos=leg_departure_isos,
                    legs=google_legs,
                )
                recomputed_records.append(
                    {
                        **record,
                        "arrivals_s": [int(v) for v in recomputed["arrivals_s"]],
                        "service_start_s": [int(v) for v in recomputed["service_start_s"]],
                        "service_end_s": [int(v) for v in recomputed["service_end_s"]],
                        "components": {
                            "route_start_s": route_start_s,
                            "route_end_s": int(recomputed["route_end_s"]),
                            "route_duration_s": int(recomputed["route_duration_s"]),
                            "travel_time_s": int(recomputed["travel_time_s"]),
                            "service_time_s": int(recomputed["service_time_s"]),
                            "waiting_time_s": int(recomputed["waiting_time_s"]),
                        },
                    }
                )

            route_records = recomputed_records
            eta_source = ETA_SOURCE_GOOGLE_TRAFFIC
            if collected_uplift_rows > 0:
                LOGGER.info("Collected %s Google leg samples for uplift training (dataset_id=%s)", collected_uplift_rows, dataset_id)
            LOGGER.info(
                "Optimization ETA source selected: %s (plan_id=%s, dataset_id=%s)",
                eta_source,
                plan.id,
                dataset_id,
            )
        except GoogleTrafficError as exc:
            warnings.append("Google traffic unavailable; using baseline ETAs.")
            if progress_cb:
                progress_cb(90, "Fallback to ML baseline due to quota/timeout ...")
            LOGGER.warning(
                "Google ETA fallback activated (plan_id=%s, dataset_id=%s, code=%s, status=%s, details=%s)",
                plan.id,
                dataset_id,
                exc.code,
                exc.status_code,
                _google_error_details_json(exc),
            )
            eta_source = _eta_source_from_artifact(artifact)
            traffic_timestamp = None
        except Exception as exc:  # noqa: BLE001
            warnings.append("Google traffic unavailable; using baseline ETAs.")
            if progress_cb:
                progress_cb(90, "Fallback to ML baseline due to quota/timeout ...")
            LOGGER.warning(
                "Google ETA fallback activated (plan_id=%s, dataset_id=%s, error_type=%s, error=%s)",
                plan.id,
                dataset_id,
                exc.__class__.__name__,
                str(exc),
            )
            eta_source = _eta_source_from_artifact(artifact)
            traffic_timestamp = None

    route_summaries = []
    route_start_times: list[int] = []
    route_end_times: list[int] = []
    total_vehicle_duration_s = 0

    for idx, record in enumerate(route_records):
        route_nodes = [int(v) for v in record["route_nodes"]]
        component = record["components"]
        total_distance = float(record["total_distance_m"])
        route_duration_s = int(component["route_duration_s"])
        route_start_times.append(int(component["route_start_s"]))
        route_end_times.append(int(component["route_end_s"]))
        total_vehicle_duration_s += route_duration_s

        route_row = Route(
            plan_id=plan.id,
            vehicle_idx=int(record["vehicle_idx"]),
            total_distance_m=total_distance,
            total_duration_s=float(route_duration_s),
        )
        db.add(route_row)
        db.flush()

        arrivals_s = [int(v) for v in record["arrivals_s"]]
        service_start_s = [int(v) for v in record["service_start_s"]]
        service_end_s = [int(v) for v in record["service_end_s"]]
        for seq, node_idx in enumerate(route_nodes):
            node = nodes[node_idx]
            stop_id = node.get("stop_id")
            tw_s, tw_e = time_windows[node_idx]
            db.add(
                RouteStop(
                    route_id=route_row.id,
                    sequence_idx=seq,
                    stop_id=int(stop_id) if stop_id is not None else None,
                    eta_iso=_seconds_to_iso(arrivals_s[seq]),
                    arrival_window_start_iso=_seconds_to_iso(tw_s),
                    arrival_window_end_iso=_seconds_to_iso(tw_e),
                    service_start_iso=_seconds_to_iso(service_start_s[seq]),
                    service_end_iso=_seconds_to_iso(service_end_s[seq]),
                )
            )

        route_summaries.append(
            {
                "vehicle_idx": int(record["vehicle_idx"]),
                "total_distance_m": round(total_distance, 2),
                "total_duration_s": int(component["route_duration_s"]),
                "travel_time_s": int(component["travel_time_s"]),
                "service_time_s": int(component["service_time_s"]),
                "waiting_time_s": int(component["waiting_time_s"]),
                "stop_count": max(0, len(route_nodes) - 2),
            }
        )
        if progress_cb:
            progress = 92 + int(((idx + 1) / max(1, len(route_records))) * 7)
            progress_cb(progress, f"Persisting route {idx + 1}/{len(route_records)}")

    plan.total_makespan_s = float(max(route_end_times) - min(route_start_times)) if route_start_times and route_end_times else 0.0
    plan.eta_source = eta_source
    plan.traffic_timestamp_iso = traffic_timestamp if eta_source == ETA_SOURCE_GOOGLE_TRAFFIC else None
    dataset.status = "OPTIMIZED"
    LOGGER.info(
        "Plan ETA source selected: %s (plan_id=%s, dataset_id=%s, live_traffic_requested=%s)",
        plan.eta_source,
        plan.id,
        dataset_id,
        bool(plan.live_traffic_requested),
    )
    db.commit()
    db.refresh(plan)
    if progress_cb:
        progress_cb(100, "Optimization complete")

    unserved_stop_ids = []
    for idx in result.unserved_nodes:
        stop_id = nodes[idx].get("stop_id")
        if stop_id is not None:
            unserved_stop_ids.append(int(stop_id))

    return {
        "plan_id": plan.id,
        "feasible": True,
        "status": plan.status,
        "objective_value": float(plan.objective_value or 0),
        "total_makespan_s": float(plan.total_makespan_s or 0),
        "sum_vehicle_durations_s": float(total_vehicle_duration_s),
        "route_summary": route_summaries,
        "unserved_stop_ids": unserved_stop_ids,
        "model_version": artifact.get("chosen_model_version"),
        "eta_source": plan.eta_source,
        "traffic_timestamp": plan.traffic_timestamp_iso,
        "live_traffic_requested": bool(plan.live_traffic_requested),
        "warnings": warnings,
    }


def resequence_route(
    db: Session,
    *,
    plan_id: int,
    route_id: int,
    ordered_stop_ids: list[int],
    depart_time_iso: str | None = None,
    apply_changes: bool = False,
    use_live_traffic: bool | None = None,
) -> dict[str, Any]:
    route = db.execute(
        select(Route).where(Route.id == route_id, Route.plan_id == plan_id).options(joinedload(Route.route_stops).joinedload(RouteStop.stop))
    ).unique().scalar_one_or_none()
    if route is None:
        raise AppError(message="Route not found", error_code="NOT_FOUND", status_code=404)

    plan = db.get(Plan, plan_id)
    if plan is None:
        raise AppError(message="Plan not found", error_code="NOT_FOUND", status_code=404)

    existing_stops = [rs.stop for rs in sorted(route.route_stops, key=lambda x: x.sequence_idx) if rs.stop_id is not None and rs.stop]
    existing_ids = [stop.id for stop in existing_stops]
    if sorted(existing_ids) != sorted(ordered_stop_ids):
        raise AppError(
            message="ordered_stop_ids must match existing route stop IDs",
            error_code="VALIDATION_ERROR",
            status_code=400,
            stage="OPTIMIZATION",
        )

    stop_by_id = {stop.id: stop for stop in existing_stops}
    ordered_stops = [stop_by_id[stop_id] for stop_id in ordered_stop_ids]

    if depart_time_iso:
        depart_dt = datetime.fromisoformat(depart_time_iso)
    else:
        workday_start = plan.workday_start or "08:00"
        depart_dt = datetime.combine(date.today(), datetime.strptime(workday_start, "%H:%M").time())

    workday_end_hhmm = plan.workday_end or "18:00"
    workday_end_dt = datetime.combine(depart_dt.date(), datetime.strptime(workday_end_hhmm, "%H:%M").time())
    workday_start_dt = datetime.combine(depart_dt.date(), datetime.strptime(plan.workday_start or "08:00", "%H:%M").time())

    routing_service = get_routing_service()
    ml_engine = get_ml_engine()
    uplift_service = get_ml_uplift_service()
    uplift_active = bool(uplift_service.enabled and uplift_service.model_available())
    day_of_week = depart_dt.weekday()

    settings = get_settings()
    live_traffic_requested = bool(plan.live_traffic_requested if use_live_traffic is None else use_live_traffic)
    google_requested = bool(settings.feature_google_traffic and live_traffic_requested)
    eta_source = ETA_SOURCE_ML_BASELINE
    traffic_timestamp: str | None = None
    warnings: list[str] = []
    ordered_nodes = [None] + ordered_stops + [None]
    google_leg_times: list[int] | None = None
    google_legs: list[Any] | None = None
    google_route_points: list[dict[str, float]] | None = None
    if live_traffic_requested and not settings.feature_google_traffic:
        warnings.append("Google traffic feature flag disabled; using baseline ETAs.")
    if google_requested:
        try:
            provider = get_google_traffic_provider()
            if not provider.enabled:
                raise GoogleTrafficError("Google traffic feature unavailable", code="GOOGLE_TRAFFIC_DISABLED")
            google_route_points = [
                {"lat": plan.depot_lat, "lon": plan.depot_lon}
                if node is None
                else {"lat": float(node.lat or 0), "lon": float(node.lon or 0)}
                for node in ordered_nodes
            ]
            google_depart_dt = _ensure_future_google_departure(depart_dt)
            google_legs = _google_route_legs(
                provider=provider,
                route_points=google_route_points,
                departure_time_iso=google_depart_dt.isoformat(),
                routing_preference=settings.resolved_google_routing_preference,
            )
            google_leg_times = [max(1, int(leg.duration_s)) for leg in google_legs]
            eta_source = ETA_SOURCE_GOOGLE_TRAFFIC
            traffic_timestamp = google_depart_dt.isoformat()
        except GoogleTrafficError as exc:
            warnings.append("Google traffic unavailable; using baseline ETAs.")
            LOGGER.warning(
                "Google resequence fallback activated (plan_id=%s, route_id=%s, code=%s, status=%s, details=%s)",
                plan_id,
                route_id,
                exc.code,
                exc.status_code,
                _google_error_details_json(exc),
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append("Google traffic unavailable; using baseline ETAs.")
            LOGGER.warning(
                "Google resequence fallback activated (plan_id=%s, route_id=%s, error_type=%s, error=%s)",
                plan_id,
                route_id,
                exc.__class__.__name__,
                str(exc),
            )

    timeline: list[dict[str, Any]] = []
    current_dt = depart_dt
    route_start_dt = depart_dt
    total_distance = 0.0
    travel_time_s = 0
    waiting_time_s = 0
    service_time_s = 0
    violations: list[dict[str, Any]] = []
    total_demand = 0
    used_ml = False
    used_uplift = False
    used_onemap = False

    timeline.append(
        {
            "sequence_idx": 0,
            "stop_id": None,
            "stop_ref": "DEPOT",
            "address": "DEPOT",
            "lat": plan.depot_lat,
            "lon": plan.depot_lon,
            "phone": None,
            "contact_name": None,
            "eta_iso": current_dt.isoformat(),
            "arrival_window_start_iso": workday_start_dt.isoformat(),
            "arrival_window_end_iso": workday_end_dt.isoformat(),
            "service_start_iso": current_dt.isoformat(),
            "service_end_iso": current_dt.isoformat(),
        }
    )

    for idx in range(1, len(ordered_nodes)):
        current_node = ordered_nodes[idx]
        prev_node = ordered_nodes[idx - 1]
        origin_lat = plan.depot_lat if prev_node is None else float(prev_node.lat or 0)
        origin_lon = plan.depot_lon if prev_node is None else float(prev_node.lon or 0)
        dest_lat = plan.depot_lat if current_node is None else float(current_node.lat or 0)
        dest_lon = plan.depot_lon if current_node is None else float(current_node.lon or 0)

        depart_bucket = current_dt.strftime("%H:%M")
        base = routing_service.get_base_route(
            db,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            dest_lat=dest_lat,
            dest_lon=dest_lon,
            depart_bucket=depart_bucket,
            day_of_week=day_of_week,
        )
        total_distance += float(base.distance_m)

        if google_leg_times is not None:
            leg_idx = idx - 1
            if leg_idx >= len(google_leg_times):
                raise AppError(
                    message="Google traffic result size mismatch",
                    error_code="GOOGLE_LEG_COUNT_MISMATCH",
                    status_code=502,
                    stage="OPTIMIZATION",
                )
            leg_travel_s = max(1, int(google_leg_times[leg_idx]))
        else:
            try:
                pred = ml_engine.predict_duration(
                    db,
                    od_cache_id=base.od_cache_id,
                    base_duration_s=base.duration_s,
                    distance_m=base.distance_m,
                    depart_dt=current_dt,
                    origin_lat=origin_lat,
                    origin_lon=origin_lon,
                    dest_lat=dest_lat,
                    dest_lon=dest_lon,
                )
                leg_travel_s = max(1, int(round(pred.duration_s)))
                used_ml = True
                if uplift_active:
                    factors = uplift_service.predict_factors(
                        [
                            uplift_service.build_inference_row(
                                origin_lat=origin_lat,
                                origin_lng=origin_lon,
                                dest_lat=dest_lat,
                                dest_lng=dest_lon,
                                distance_m=float(base.distance_m),
                                departure_time_iso=current_dt.isoformat(),
                                static_duration_s=float(base.duration_s),
                            )
                        ]
                    )
                    if factors:
                        leg_travel_s = max(1, int(round(float(leg_travel_s) * float(factors[0]))))
                        used_uplift = True
            except Exception as exc:  # noqa: BLE001
                leg_travel_s = max(1, int(round(float(base.duration_s))))
                used_onemap = True
                LOGGER.warning(
                    "Resequence leg fallback to OneMap duration (plan_id=%s, route_id=%s, idx=%s, error=%s)",
                    plan_id,
                    route_id,
                    idx,
                    str(exc),
                )

        travel_time_s += leg_travel_s
        arrival_dt = current_dt + timedelta(seconds=leg_travel_s)

        if current_node is None:
            timeline.append(
                {
                    "sequence_idx": idx,
                    "stop_id": None,
                    "stop_ref": "DEPOT",
                    "address": "DEPOT",
                    "lat": plan.depot_lat,
                    "lon": plan.depot_lon,
                    "phone": None,
                    "contact_name": None,
                    "eta_iso": arrival_dt.isoformat(),
                    "arrival_window_start_iso": workday_start_dt.isoformat(),
                    "arrival_window_end_iso": workday_end_dt.isoformat(),
                    "service_start_iso": arrival_dt.isoformat(),
                    "service_end_iso": arrival_dt.isoformat(),
                }
            )
            current_dt = arrival_dt
            continue

        total_demand += int(current_node.demand or 0)
        service_s = int(current_node.service_time_min or 0) * 60
        service_time_s += service_s

        if current_node.tw_start and current_node.tw_end:
            tw_start = datetime.combine(depart_dt.date(), datetime.strptime(current_node.tw_start, "%H:%M").time())
            tw_end = datetime.combine(depart_dt.date(), datetime.strptime(current_node.tw_end, "%H:%M").time())
        else:
            tw_start = workday_start_dt
            tw_end = workday_end_dt

        service_start_dt = max(arrival_dt, tw_start)
        wait_s = max(0, int((service_start_dt - arrival_dt).total_seconds()))
        waiting_time_s += wait_s
        service_end_dt = service_start_dt + timedelta(seconds=service_s)

        if arrival_dt > tw_end:
            violations.append(
                {
                    "type": "TIME_WINDOW",
                    "stop_id": current_node.id,
                    "stop_ref": current_node.stop_ref,
                    "message": f"Arrival {arrival_dt.strftime('%H:%M')} exceeds time window end {tw_end.strftime('%H:%M')}",
                }
            )
        if service_end_dt > workday_end_dt:
            violations.append(
                {
                    "type": "WORKDAY_END",
                    "stop_id": current_node.id,
                    "stop_ref": current_node.stop_ref,
                    "message": f"Service end {service_end_dt.strftime('%H:%M')} exceeds workday end {workday_end_dt.strftime('%H:%M')}",
                }
            )

        timeline.append(
            {
                "sequence_idx": idx,
                "stop_id": current_node.id,
                "stop_ref": current_node.stop_ref,
                "address": current_node.address,
                "lat": current_node.lat,
                "lon": current_node.lon,
                "phone": current_node.phone,
                "contact_name": current_node.contact_name,
                "eta_iso": service_start_dt.isoformat(),
                "arrival_window_start_iso": tw_start.isoformat(),
                "arrival_window_end_iso": tw_end.isoformat(),
                "service_start_iso": service_start_dt.isoformat(),
                "service_end_iso": service_end_dt.isoformat(),
            }
        )
        current_dt = service_end_dt

    if google_legs is not None and google_route_points is not None:
        leg_departure_isos = [timeline[idx]["service_end_iso"] for idx in range(max(0, len(timeline) - 1))]
        collected = uplift_service.collect_google_leg_samples(
            route_points=google_route_points,
            leg_departure_isos=leg_departure_isos,
            legs=google_legs,
        )
        if collected > 0:
            LOGGER.info("Collected %s Google leg samples from resequence (plan_id=%s, route_id=%s)", collected, plan_id, route_id)

    if google_leg_times is None:
        if used_onemap:
            eta_source = ETA_SOURCE_ONEMAP
        elif used_uplift:
            eta_source = ETA_SOURCE_ML_UPLIFT
        elif used_ml:
            eta_source = ETA_SOURCE_ML_BASELINE
        else:
            eta_source = ETA_SOURCE_ONEMAP

    if plan.vehicle_capacity is not None and total_demand > plan.vehicle_capacity:
        violations.append(
            {
                "type": "CAPACITY",
                "message": f"Total route demand {total_demand} exceeds vehicle capacity {plan.vehicle_capacity}",
            }
        )

    route_duration_s = max(0, int((current_dt - route_start_dt).total_seconds()))
    suggestions: list[str] = []
    if any(v["type"] == "TIME_WINDOW" for v in violations):
        suggestions.append("Try swapping nearby stops with tight time windows.")
    if any(v["type"] == "WORKDAY_END" for v in violations):
        suggestions.append("Start earlier or reduce stop count for this vehicle.")
    if any(v["type"] == "CAPACITY" for v in violations):
        suggestions.append("Move high-demand stops to another vehicle.")

    if apply_changes:
        route.total_distance_m = float(total_distance)
        route.total_duration_s = float(route_duration_s)
        db.execute(delete(RouteStop).where(RouteStop.route_id == route.id))
        db.flush()
        for row in timeline:
            db.add(
                RouteStop(
                    route_id=route.id,
                    sequence_idx=int(row["sequence_idx"]),
                    stop_id=row["stop_id"],
                    eta_iso=row["eta_iso"],
                    arrival_window_start_iso=row["arrival_window_start_iso"],
                    arrival_window_end_iso=row["arrival_window_end_iso"],
                    service_start_iso=row["service_start_iso"],
                    service_end_iso=row["service_end_iso"],
                )
            )
        plan.eta_source = eta_source
        plan.traffic_timestamp_iso = traffic_timestamp if eta_source == ETA_SOURCE_GOOGLE_TRAFFIC else None
        plan.live_traffic_requested = bool(live_traffic_requested)
        plan.updated_at = datetime.utcnow()

        other_routes = db.execute(select(Route).where(Route.plan_id == plan_id).options(joinedload(Route.route_stops))).unique().scalars().all()
        route_starts: list[datetime] = []
        route_ends: list[datetime] = []
        for r in other_routes:
            sorted_rs = sorted(r.route_stops, key=lambda x: x.sequence_idx)
            if not sorted_rs:
                continue
            try:
                route_starts.append(datetime.fromisoformat(sorted_rs[0].eta_iso or ""))
                route_ends.append(datetime.fromisoformat(sorted_rs[-1].eta_iso or ""))
            except ValueError:
                continue
        if route_starts and route_ends:
            plan.total_makespan_s = float((max(route_ends) - min(route_starts)).total_seconds())

        db.commit()

    LOGGER.info(
        "Resequence ETA source selected: %s (plan_id=%s, route_id=%s, apply=%s, live_traffic_requested=%s)",
        eta_source,
        plan_id,
        route_id,
        bool(apply_changes),
        bool(live_traffic_requested),
    )

    return {
        "plan_id": plan_id,
        "route_id": route_id,
        "apply": apply_changes,
        "totals": {
            "total_distance_m": round(total_distance, 2),
            "total_duration_s": route_duration_s,
            "travel_time_s": travel_time_s,
            "service_time_s": service_time_s,
            "waiting_time_s": waiting_time_s,
            "demand": total_demand,
        },
        "violations": violations,
        "suggestions": suggestions,
        "stops": timeline,
        "eta_source": eta_source,
        "traffic_timestamp": traffic_timestamp if eta_source == ETA_SOURCE_GOOGLE_TRAFFIC else None,
        "live_traffic_requested": bool(live_traffic_requested),
        "warnings": warnings,
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
    sum_vehicle_durations_s = 0.0

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
                    "phone": stop.phone if stop else None,
                    "contact_name": stop.contact_name if stop else None,
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
        sum_vehicle_durations_s += float(route.total_duration_s or 0)

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
        "total_makespan_s": float(plan.total_makespan_s or 0) if plan.total_makespan_s is not None else None,
        "sum_vehicle_durations_s": float(sum_vehicle_durations_s),
        "infeasibility_reason": plan.infeasibility_reason,
        "depot": {"lat": plan.depot_lat, "lon": plan.depot_lon},
        "routes": routes_payload,
        "unserved_stops": unserved,
        "eta_source": plan.eta_source,
        "traffic_timestamp": plan.traffic_timestamp_iso,
        "live_traffic_requested": bool(plan.live_traffic_requested),
    }
