from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from datetime import date, datetime
from typing import Any, Callable

from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dataset, Stop
from app.services.ml_engine import get_ml_engine
from app.services.ml_ops import choose_model_version_for_prediction
from app.services.optimization import OptimizationPayload, calculate_route_duration_components
from app.services.routing import get_routing_service
from app.services.vrptw import SolverResult, solve_vrptw
from app.utils.errors import AppError


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


def _improvement_pct(baseline: float, model: float, *, higher_is_better: bool) -> float | None:
    if abs(baseline) < 1e-9:
        return None
    if higher_is_better:
        return float(((model - baseline) / abs(baseline)) * 100.0)
    return float(((baseline - model) / abs(baseline)) * 100.0)


def _summarize_solver(
    *,
    solver_result: SolverResult,
    travel_time_matrix: list[list[int]],
    distance_matrix: list[list[float]],
    time_windows: list[tuple[int, int]],
    service_times_s: list[int],
    total_stops: int,
) -> dict[str, Any]:
    if not solver_result.feasible:
        return {
            "feasible": False,
            "objective": 0,
            "served_count": 0,
            "served_ratio": 0.0,
            "unserved_count": total_stops,
            "total_distance_m": 0.0,
            "makespan_s": 0.0,
            "sum_vehicle_duration_s": 0.0,
            "avg_waiting_s": 0.0,
            "on_time_rate": 0.0,
            "route_summaries": [],
        }

    total_distance = 0.0
    total_vehicle_duration = 0.0
    total_waiting = 0
    route_starts: list[int] = []
    route_ends: list[int] = []
    on_time = 0
    served_for_ontime = 0
    route_summaries: list[dict[str, Any]] = []

    for vehicle_idx, route_nodes in enumerate(solver_result.routes):
        arrivals = solver_result.arrivals[vehicle_idx]
        for a, b in zip(route_nodes[:-1], route_nodes[1:]):
            total_distance += float(distance_matrix[a][b])

        components = calculate_route_duration_components(
            route_nodes=route_nodes,
            route_arrivals=arrivals,
            service_times_s=service_times_s,
            travel_time_matrix_s=travel_time_matrix,
        )
        total_vehicle_duration += float(components["route_duration_s"])
        total_waiting += int(components["waiting_time_s"])
        route_starts.append(int(components["route_start_s"]))
        route_ends.append(int(components["route_end_s"]))

        stop_count = 0
        for seq, node_idx in enumerate(route_nodes):
            if node_idx == 0:
                continue
            stop_count += 1
            served_for_ontime += 1
            arrival = arrivals[seq]
            _, tw_end = time_windows[node_idx]
            if int(arrival) <= int(tw_end):
                on_time += 1

        route_summaries.append(
            {
                "vehicle_idx": vehicle_idx,
                "stop_count": stop_count,
                "total_duration_s": int(components["route_duration_s"]),
                "travel_time_s": int(components["travel_time_s"]),
                "service_time_s": int(components["service_time_s"]),
                "waiting_time_s": int(components["waiting_time_s"]),
            }
        )

    unserved = len(solver_result.unserved_nodes)
    served = max(0, total_stops - unserved)
    makespan = float(max(route_ends) - min(route_starts)) if route_starts and route_ends else 0.0
    on_time_rate = float(on_time / served_for_ontime) if served_for_ontime > 0 else 0.0
    avg_waiting = float(total_waiting / max(1, served))

    return {
        "feasible": True,
        "objective": int(solver_result.objective),
        "served_count": int(served),
        "served_ratio": float(served / max(1, total_stops)),
        "unserved_count": int(unserved),
        "total_distance_m": round(total_distance, 2),
        "makespan_s": float(makespan),
        "sum_vehicle_duration_s": float(total_vehicle_duration),
        "avg_waiting_s": float(avg_waiting),
        "on_time_rate": float(on_time_rate),
        "route_summaries": route_summaries,
    }


def run_ab_simulation(
    db: Session,
    *,
    dataset_id: int,
    payload: OptimizationPayload,
    model_version: str | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError(message=f"Dataset {dataset_id} not found", error_code="NOT_FOUND", status_code=404)

    stops = db.execute(
        select(Stop).where(Stop.dataset_id == dataset_id, Stop.geocode_status.in_(["SUCCESS", "MANUAL"]))
    ).scalars().all()
    if not stops:
        raise AppError(
            message="No geocoded stops available for A/B simulation",
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

    depot_lat, depot_lon = _ensure_wgs84(payload.depot_lat, payload.depot_lon)
    nodes: list[dict[str, Any]] = [{"kind": "depot", "lat": depot_lat, "lon": depot_lon, "stop": None}]
    for stop in stops:
        if stop.lat is None or stop.lon is None:
            continue
        stop_lat, stop_lon = _ensure_wgs84(stop.lat, stop.lon)
        nodes.append({"kind": "stop", "lat": stop_lat, "lon": stop_lon, "stop": stop})

    total_stops = len(nodes) - 1
    n = len(nodes)
    if n <= 1:
        raise AppError(message="No valid nodes for simulation", error_code="VALIDATION_ERROR", status_code=400)

    depart_bucket = payload.workday_start
    day_of_week = datetime.utcnow().weekday()
    depart_dt = datetime.combine(date.today(), datetime.strptime(payload.workday_start, "%H:%M").time())

    if progress_cb:
        progress_cb(5, "Building shared base OD matrix")

    routing_service = get_routing_service()
    ml_engine = get_ml_engine()

    base_duration_matrix = [[0.0 for _ in range(n)] for _ in range(n)]
    distance_matrix = [[0.0 for _ in range(n)] for _ in range(n)]
    od_id_matrix = [[-1 for _ in range(n)] for _ in range(n)]
    pair_total = max(1, n * n - n)
    pair_done = 0
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            o = nodes[i]
            d = nodes[j]
            base = routing_service.get_base_route(
                db,
                origin_lat=float(o["lat"]),
                origin_lon=float(o["lon"]),
                dest_lat=float(d["lat"]),
                dest_lon=float(d["lon"]),
                depart_bucket=depart_bucket,
                day_of_week=day_of_week,
            )
            base_duration_matrix[i][j] = float(base.duration_s)
            distance_matrix[i][j] = float(base.distance_m)
            od_id_matrix[i][j] = int(base.od_cache_id)
            pair_done += 1
            if progress_cb and (pair_done % max(1, pair_total // 20) == 0 or pair_done == pair_total):
                progress_cb(5 + int((pair_done / pair_total) * 35), f"OD matrix {pair_done}/{pair_total}")

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

    selected_model = model_version or choose_model_version_for_prediction(db) or "fallback_v1"

    def build_time_matrix(strategy: str) -> tuple[list[list[int]], str]:
        matrix = [[0 for _ in range(n)] for _ in range(n)]
        used_version = "fallback_v1"
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                o = nodes[i]
                d = nodes[j]
                pred = ml_engine.predict_duration(
                    db,
                    od_cache_id=int(od_id_matrix[i][j]),
                    base_duration_s=float(base_duration_matrix[i][j]),
                    distance_m=float(distance_matrix[i][j]),
                    depart_dt=depart_dt,
                    origin_lat=float(o["lat"]),
                    origin_lon=float(o["lon"]),
                    dest_lat=float(d["lat"]),
                    dest_lon=float(d["lon"]),
                    strategy="fallback" if strategy == "baseline" else "model",
                    force_model_version=None if strategy == "baseline" else selected_model,
                    log_prediction=False,
                )
                matrix[i][j] = max(1, int(round(pred.duration_s)))
                used_version = pred.model_version
        return matrix, used_version

    if progress_cb:
        progress_cb(45, "Predicting baseline time matrix")
    baseline_matrix, baseline_version = build_time_matrix("baseline")

    if progress_cb:
        progress_cb(60, "Predicting ML time matrix")
    ml_matrix, ml_version = build_time_matrix("model")

    if progress_cb:
        progress_cb(72, "Solving baseline VRPTW")
    baseline_result = solve_vrptw(
        time_matrix=baseline_matrix,
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

    if progress_cb:
        progress_cb(84, "Solving ML VRPTW")
    ml_result = solve_vrptw(
        time_matrix=ml_matrix,
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

    baseline_summary = _summarize_solver(
        solver_result=baseline_result,
        travel_time_matrix=baseline_matrix,
        distance_matrix=distance_matrix,
        time_windows=time_windows,
        service_times_s=service_times,
        total_stops=total_stops,
    )
    ml_summary = _summarize_solver(
        solver_result=ml_result,
        travel_time_matrix=ml_matrix,
        distance_matrix=distance_matrix,
        time_windows=time_windows,
        service_times_s=service_times,
        total_stops=total_stops,
    )

    kpi_defs = [
        ("served_ratio", "Served Ratio", True),
        ("on_time_rate", "On-Time Rate", True),
        ("makespan_s", "Total Makespan (s)", False),
        ("sum_vehicle_duration_s", "Sum Vehicle Durations (s)", False),
        ("total_distance_m", "Total Distance (m)", False),
        ("unserved_count", "Unserved Stops", False),
    ]

    comparison = []
    for key, label, higher_better in kpi_defs:
        baseline_value = float(baseline_summary.get(key, 0.0))
        ml_value = float(ml_summary.get(key, 0.0))
        comparison.append(
            {
                "key": key,
                "label": label,
                "higher_is_better": higher_better,
                "baseline": baseline_value,
                "ml": ml_value,
                "improvement_pct": _improvement_pct(baseline_value, ml_value, higher_is_better=higher_better),
            }
        )

    if progress_cb:
        progress_cb(100, "A/B simulation complete")

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "dataset_id": dataset_id,
        "samples": total_stops,
        "baseline_version": baseline_version,
        "ml_version": ml_version,
        "baseline": baseline_summary,
        "ml": ml_summary,
        "comparison": comparison,
    }


def _draw_ab_plot_png(comparison: list[dict[str, Any]]) -> bytes:
    width, height = 1200, 700
    img = Image.new("RGB", (width, height), (248, 250, 252))
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 40, width - 40, height - 40), outline=(210, 218, 227), fill=(255, 255, 255), width=2)
    draw.text((60, 60), "Optimization A/B Simulation (Baseline vs ML)", fill=(17, 24, 39))

    base_x = 70
    start_y = 130
    row_h = 85
    max_bar = 360
    max_val = 1.0
    plot_rows = comparison[:5]
    for row in plot_rows:
        max_val = max(max_val, abs(float(row.get("baseline", 0.0))), abs(float(row.get("ml", 0.0))))

    for idx, row in enumerate(plot_rows):
        y = start_y + idx * row_h
        label = row.get("label", row.get("key", "KPI"))
        b = float(row.get("baseline", 0.0))
        m = float(row.get("ml", 0.0))
        b_w = int((abs(b) / max_val) * max_bar)
        m_w = int((abs(m) / max_val) * max_bar)

        draw.text((base_x, y), str(label), fill=(30, 41, 59))
        draw.rectangle((base_x + 280, y + 8, base_x + 280 + b_w, y + 30), fill=(100, 116, 139))
        draw.rectangle((base_x + 280, y + 38, base_x + 280 + m_w, y + 60), fill=(16, 152, 105))
        draw.text((base_x + 650, y + 8), f"Baseline: {b:.2f}", fill=(51, 65, 85))
        draw.text((base_x + 650, y + 38), f"ML: {m:.2f}", fill=(5, 150, 105))

    draw.rectangle((width - 330, 100, width - 70, 170), outline=(203, 213, 225), fill=(255, 255, 255))
    draw.rectangle((width - 315, 118, width - 295, 138), fill=(100, 116, 139))
    draw.text((width - 285, 116), "Baseline", fill=(17, 24, 39))
    draw.rectangle((width - 315, 145, width - 295, 165), fill=(16, 152, 105))
    draw.text((width - 285, 143), "ML", fill=(17, 24, 39))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_ab_report_zip(report: dict[str, Any]) -> bytes:
    summary_csv = io.StringIO()
    writer = csv.writer(summary_csv)
    writer.writerow(["kpi_key", "kpi_label", "baseline", "ml", "improvement_pct", "higher_is_better"])
    for row in report.get("comparison", []):
        writer.writerow(
            [
                row.get("key"),
                row.get("label"),
                row.get("baseline"),
                row.get("ml"),
                row.get("improvement_pct"),
                row.get("higher_is_better"),
            ]
        )

    route_csv = io.StringIO()
    writer = csv.writer(route_csv)
    writer.writerow(["variant", "vehicle_idx", "stop_count", "total_duration_s", "travel_time_s", "service_time_s", "waiting_time_s"])
    for variant in ("baseline", "ml"):
        for row in report.get(variant, {}).get("route_summaries", []):
            writer.writerow(
                [
                    variant,
                    row.get("vehicle_idx"),
                    row.get("stop_count"),
                    row.get("total_duration_s"),
                    row.get("travel_time_s"),
                    row.get("service_time_s"),
                    row.get("waiting_time_s"),
                ]
            )

    chart_png = _draw_ab_plot_png(report.get("comparison", []))

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ab_kpi_summary.csv", summary_csv.getvalue())
        zf.writestr("ab_route_breakdown.csv", route_csv.getvalue())
        zf.writestr("ab_plot.png", chart_png)
        zf.writestr("ab_report.json", json.dumps(report, indent=2))
    zip_buf.seek(0)
    return zip_buf.read()

