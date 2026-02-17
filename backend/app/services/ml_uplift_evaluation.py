from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, datetime, time, timedelta
from typing import Any, Callable

import pandas as pd
from sqlalchemy.orm import Session

from app.ml_uplift.model import evaluate_uplift_predictions, load_uplift_artifact
from app.ml_uplift.schema import UPLIFT_FEATURE_COLUMNS
from app.ml_uplift.storage import read_samples_df
from app.services.optimization import (
    OptimizationPayload,
    build_optimization_matrix_artifact,
    eta_recompute_with_time_windows,
)
from app.services.traffic_provider_google import GoogleTrafficError, get_google_traffic_provider
from app.services.vrptw import solve_vrptw
from app.utils.settings import get_settings


def _seconds_to_iso(seconds_since_midnight: int) -> str:
    base = datetime.combine(date.today(), time.min)
    dt = base + timedelta(seconds=int(seconds_since_midnight))
    return dt.isoformat()


def _improvement_pct(baseline: float, model: float, *, higher_is_better: bool) -> float | None:
    if abs(float(baseline)) < 1e-9:
        return None
    if higher_is_better:
        return float(((float(model) - float(baseline)) / abs(float(baseline))) * 100.0)
    return float(((float(baseline) - float(model)) / abs(float(baseline))) * 100.0)


def _matrix_to_int(base_matrix: list[list[float]]) -> list[list[int]]:
    output = [[0 for _ in row] for row in base_matrix]
    for i, row in enumerate(base_matrix):
        for j, value in enumerate(row):
            if i == j:
                continue
            output[i][j] = max(1, int(round(float(value))))
    return output


def evaluate_prediction_accuracy(*, limit: int = 5000) -> dict[str, Any]:
    df = read_samples_df()
    if df.empty:
        return {
            "samples": 0,
            "model_version": None,
            "baseline": "static_duration_s",
            "metrics": {"baseline_metrics": {"mae_s": 0.0, "mape_pct": 0.0}, "ml_metrics": {"mae_s": 0.0, "mape_pct": 0.0}},
            "segments": [],
            "note": "No uplift samples available. Run optimization with Google ETA refinement first.",
        }

    eval_df = df.tail(max(1, int(limit))).copy()
    artifact = load_uplift_artifact()
    model_version = None
    if artifact and artifact.get("pipeline") is not None:
        pipeline = artifact["pipeline"]
        pred_factor = pd.Series(pipeline.predict(eval_df[UPLIFT_FEATURE_COLUMNS]), index=eval_df.index)
        model_version = str(artifact.get("version") or "unknown")
    else:
        pred_factor = pd.Series([1.0 for _ in range(len(eval_df))], index=eval_df.index)

    metrics = evaluate_uplift_predictions(eval_df, pred_factor=pred_factor)
    return {
        "samples": int(metrics.get("samples", 0)),
        "model_version": model_version,
        "baseline": "static_duration_s",
        "metrics": metrics,
        "segments": metrics.get("segments", []),
    }


def _simulate_execution_reference(
    *,
    artifact: dict[str, Any],
    solver_result: Any,
    fallback_matrix: list[list[int]],
) -> dict[str, Any]:
    if not solver_result.feasible:
        return {
            "feasible": False,
            "late_stops_count": 0,
            "served_stops_count": 0,
            "on_time_rate": 0.0,
            "overtime_minutes": 0.0,
            "makespan_s": 0.0,
            "reference_routes_google_count": 0,
            "reference_routes_fallback_count": 0,
            "warnings": ["VRPTW solution infeasible for this variant."],
        }

    settings = get_settings()
    provider = get_google_traffic_provider()
    nodes = artifact.get("nodes", [])
    time_windows = [tuple(map(int, pair)) for pair in artifact.get("time_windows", [])]
    service_times = [int(v) for v in artifact.get("service_times_s", [])]
    workday_window_raw = artifact.get("workday_window", [0, 24 * 3600])
    workday_end_s = int(workday_window_raw[1])

    route_start_times: list[int] = []
    route_end_times: list[int] = []
    late_stops = 0
    served_stops = 0
    overtime_minutes = 0.0
    google_ref_routes = 0
    fallback_ref_routes = 0
    warnings: list[str] = []

    for route_idx, route_nodes in enumerate(solver_result.routes):
        if len(route_nodes) < 2:
            continue
        arrivals = solver_result.arrivals[route_idx]
        route_start_s = int(arrivals[0]) if arrivals else int(workday_window_raw[0])
        route_start_times.append(route_start_s)

        route_points = [
            {"lat": float(nodes[int(node_idx)]["lat"]), "lon": float(nodes[int(node_idx)]["lon"])}
            for node_idx in route_nodes
        ]
        leg_times = [
            max(1, int(fallback_matrix[int(a)][int(b)]))
            for a, b in zip(route_nodes[:-1], route_nodes[1:])
        ]

        if provider.enabled:
            try:
                google_legs = provider.compute_routes(
                    route_points,
                    _seconds_to_iso(route_start_s),
                    routing_preference=settings.resolved_google_routing_preference,
                    include_polyline=False,
                )
                leg_times = [max(1, int(leg.duration_s)) for leg in google_legs]
                google_ref_routes += 1
            except GoogleTrafficError as exc:
                fallback_ref_routes += 1
                warnings.append(f"Google reference fallback: {exc.code}")
            except Exception:
                fallback_ref_routes += 1
                warnings.append("Google reference fallback: unexpected error")
        else:
            fallback_ref_routes += 1

        recomputed = eta_recompute_with_time_windows(
            route_nodes=[int(v) for v in route_nodes],
            route_start_s=route_start_s,
            leg_travel_s=leg_times,
            time_windows=time_windows,
            service_times_s=service_times,
        )
        route_end_s = int(recomputed["route_end_s"])
        route_end_times.append(route_end_s)
        overtime_minutes += max(0.0, float(route_end_s - workday_end_s) / 60.0)

        for seq, node_idx in enumerate(route_nodes):
            node = int(node_idx)
            if node == 0:
                continue
            served_stops += 1
            _, tw_end = time_windows[node]
            arrival_s = int(recomputed["arrivals_s"][seq])
            if arrival_s > int(tw_end):
                late_stops += 1

    makespan_s = float(max(route_end_times) - min(route_start_times)) if route_start_times and route_end_times else 0.0
    on_time_rate = float((served_stops - late_stops) / served_stops) if served_stops > 0 else 0.0
    return {
        "feasible": True,
        "late_stops_count": int(late_stops),
        "served_stops_count": int(served_stops),
        "on_time_rate": float(on_time_rate),
        "overtime_minutes": float(overtime_minutes),
        "makespan_s": float(makespan_s),
        "reference_routes_google_count": int(google_ref_routes),
        "reference_routes_fallback_count": int(fallback_ref_routes),
        "warnings": warnings,
    }


def evaluate_planning_kpis(
    db: Session,
    *,
    dataset_id: int,
    payload: OptimizationPayload,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    if progress_cb:
        progress_cb(15, "Building baseline artifact")
    baseline_artifact = build_optimization_matrix_artifact(
        db,
        dataset_id=dataset_id,
        payload=payload,
        force_uplift=False,
    )

    if progress_cb:
        progress_cb(30, "Building ML uplift artifact")
    ml_artifact = build_optimization_matrix_artifact(
        db,
        dataset_id=dataset_id,
        payload=payload,
        force_uplift=True,
    )

    baseline_matrix = _matrix_to_int(baseline_artifact.get("base_duration_matrix_s", []))
    ml_matrix = [
        [max(0, int(v)) for v in row]
        for row in ml_artifact.get("duration_matrix_s", [])
    ]
    time_windows = [tuple(map(int, pair)) for pair in baseline_artifact.get("time_windows", [])]
    service_times = [int(v) for v in baseline_artifact.get("service_times_s", [])]
    demands = [int(v) for v in baseline_artifact.get("demands", [])]
    workday_window_raw = baseline_artifact.get("workday_window", [0, 24 * 3600])
    workday_window = (int(workday_window_raw[0]), int(workday_window_raw[1]))

    if progress_cb:
        progress_cb(45, "Solving baseline VRPTW")
    baseline_solver = solve_vrptw(
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
        progress_cb(60, "Solving ML uplift VRPTW")
    ml_solver = solve_vrptw(
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

    if progress_cb:
        progress_cb(75, "Simulating baseline execution with Google reference")
    baseline_execution = _simulate_execution_reference(
        artifact=baseline_artifact,
        solver_result=baseline_solver,
        fallback_matrix=baseline_matrix,
    )

    if progress_cb:
        progress_cb(90, "Simulating ML execution with Google reference")
    ml_execution = _simulate_execution_reference(
        artifact=ml_artifact,
        solver_result=ml_solver,
        fallback_matrix=ml_matrix,
    )

    comparison_defs = [
        ("late_stops_count", "Late Stops", False),
        ("on_time_rate", "On-Time Rate", True),
        ("overtime_minutes", "Overtime Minutes", False),
        ("makespan_s", "Makespan (s)", False),
    ]
    comparison = []
    for key, label, higher_is_better in comparison_defs:
        baseline_value = float(baseline_execution.get(key, 0.0))
        ml_value = float(ml_execution.get(key, 0.0))
        comparison.append(
            {
                "key": key,
                "label": label,
                "higher_is_better": higher_is_better,
                "baseline": baseline_value,
                "ml": ml_value,
                "improvement_pct": _improvement_pct(baseline_value, ml_value, higher_is_better=higher_is_better),
            }
        )

    on_time_delta = float(ml_execution.get("on_time_rate", 0.0) - baseline_execution.get("on_time_rate", 0.0)) * 100.0
    overtime_delta = float(baseline_execution.get("overtime_minutes", 0.0) - ml_execution.get("overtime_minutes", 0.0))
    summary = (
        f"ML uplift changed on-time rate by {on_time_delta:+.2f} pts and overtime by {overtime_delta:+.2f} minutes "
        "against baseline under Google reference simulation."
    )

    return {
        "baseline": baseline_execution,
        "ml": ml_execution,
        "comparison": comparison,
        "summary": summary,
        "baseline_matrix_source": "static_duration",
        "ml_matrix_source": ml_artifact.get("matrix_strategy", "ml_baseline"),
        "uplift_model_version": ml_artifact.get("uplift_model_version"),
    }


def run_uplift_evaluation(
    db: Session,
    *,
    dataset_id: int,
    payload: OptimizationPayload,
    limit: int = 5000,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    if progress_cb:
        progress_cb(5, "Evaluating travel-time prediction accuracy")
    prediction = evaluate_prediction_accuracy(limit=limit)
    planning = evaluate_planning_kpis(db, dataset_id=dataset_id, payload=payload, progress_cb=progress_cb)
    if progress_cb:
        progress_cb(100, "Evaluation complete")
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "dataset_id": int(dataset_id),
        "prediction": prediction,
        "planning": planning,
        "summary": planning.get("summary"),
    }


def build_uplift_evaluation_report_zip(report: dict[str, Any]) -> bytes:
    prediction = report.get("prediction") or {}
    planning = report.get("planning") or {}

    summary_csv = io.StringIO()
    writer = csv.writer(summary_csv)
    writer.writerow(["section", "key", "baseline", "ml", "improvement_pct"])
    for row in planning.get("comparison", []):
        writer.writerow(["planning", row.get("key"), row.get("baseline"), row.get("ml"), row.get("improvement_pct")])
    pred_metrics = prediction.get("metrics", {})
    baseline_m = pred_metrics.get("baseline_metrics", {})
    ml_m = pred_metrics.get("ml_metrics", {})
    writer.writerow(["prediction", "mae_s", baseline_m.get("mae_s"), ml_m.get("mae_s"), pred_metrics.get("mae_improvement_pct")])
    writer.writerow(["prediction", "mape_pct", baseline_m.get("mape_pct"), ml_m.get("mape_pct"), pred_metrics.get("mape_improvement_pct")])

    segment_csv = io.StringIO()
    writer = csv.writer(segment_csv)
    writer.writerow(
        [
            "segment",
            "count",
            "baseline_mae_s",
            "ml_mae_s",
            "baseline_mape_pct",
            "ml_mape_pct",
            "mae_improvement_pct",
            "mape_improvement_pct",
        ]
    )
    for row in prediction.get("segments", []):
        writer.writerow(
            [
                row.get("segment"),
                row.get("count"),
                row.get("baseline_mae_s"),
                row.get("ml_mae_s"),
                row.get("baseline_mape_pct"),
                row.get("ml_mape_pct"),
                row.get("mae_improvement_pct"),
                row.get("mape_improvement_pct"),
            ]
        )

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("evaluation_summary.csv", summary_csv.getvalue())
        zip_file.writestr("prediction_segments.csv", segment_csv.getvalue())
        zip_file.writestr("evaluation_report.json", json.dumps(report, indent=2))
    out_buf.seek(0)
    return out_buf.read()

