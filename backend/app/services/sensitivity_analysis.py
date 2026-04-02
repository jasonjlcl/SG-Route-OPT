from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from dataclasses import asdict, dataclass
from datetime import date
from html import escape
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Dataset, MLModel, Stop
from app.services.datasets import create_dataset_from_upload
from app.services.geocoding import geocode_dataset, manual_resolve_stop
from app.services.optimization import OptimizationPayload
from app.services.optimization_experiments import run_ab_simulation


BACKEND_DIR = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = BACKEND_DIR / "app" / "ml" / "artifacts"

DEFAULT_CALIBRATED_MODEL_VERSION = "v20260315063821017757"
DEFAULT_DEPOT_LAT = 1.3521
DEFAULT_DEPOT_LON = 103.8198
DEFAULT_SOLVER_TIME_LIMIT_S = 8
TIGHTER_WINDOW_TOTAL_SHRINK_MINUTES = 60
TIGHTER_WINDOW_MIN_WIDTH_MINUTES = 60

SVG_WIDTH = 1440
SVG_HEIGHT = 860
SVG_BG = "#F6F1E8"
SVG_INK = "#182026"
SVG_GRID = "#D6D1C7"
SVG_AXIS = "#7B7F82"
SVG_FALLBACK = "#0F4C5C"
SVG_CALIBRATED = "#3A7D44"


@dataclass(frozen=True)
class SensitivityScenario:
    scenario_id: str
    scenario_label: str
    factor_changed: str
    factor_value: str
    num_vehicles: int
    vehicle_capacity: int | None
    workday_start: str
    workday_end: str
    allow_drop_visits: bool
    service_time_scale: float
    time_window_mode: str


@dataclass
class SensitivityRow:
    scenario_id: str
    scenario_label: str
    factor_changed: str
    factor_value: str
    travel_time_source: str
    model_version: str
    source_dataset_id: int
    scenario_dataset_id: int
    num_vehicles: int
    vehicle_capacity: int | None
    workday_start: str
    workday_end: str
    allow_drop_visits: bool
    service_time_scale: float
    time_window_mode: str
    makespan_seconds: float
    total_distance_m: float
    served_stops: int
    total_stops: int
    on_time_rate: float
    late_stops: int
    dropped_stops: int
    solver_status: str
    solve_time_seconds: float | None
    feasible: bool
    objective_value: float
    sum_vehicle_duration_seconds: float
    avg_waiting_seconds: float


@dataclass(frozen=True)
class PlotArea:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def _build_session_factory(db_path: Path) -> sessionmaker[Session]:
    db_url = f"sqlite:///{db_path.resolve().as_posix()}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False, "timeout": 30}, future=True)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _ensure_model_row(db: Session, version: str) -> None:
    existing = db.execute(select(MLModel).where(MLModel.version == version)).scalar_one_or_none()
    if existing is not None:
        return

    version_dir = ARTIFACT_DIR / version
    model_path = version_dir / "model.pkl"
    if not model_path.exists():
        fallback = ARTIFACT_DIR / f"model_{version}.joblib"
        if fallback.exists():
            model_path = fallback
        else:
            raise FileNotFoundError(f"Missing local artifact for model version {version}")

    feature_schema_json = None
    feature_schema_path = version_dir / "feature_schema.json"
    if feature_schema_path.exists():
        feature_schema_json = feature_schema_path.read_text(encoding="utf-8")

    metrics_json = None
    metrics_path = version_dir / "metrics.json"
    if metrics_path.exists():
        metrics_json = metrics_path.read_text(encoding="utf-8")

    db.add(
        MLModel(
            version=version,
            artifact_path=str(model_path),
            feature_schema_json=feature_schema_json,
            metrics_json=metrics_json,
            training_data_ref=None,
            status="TRAINED",
        )
    )
    db.commit()


def _failed_stop_ids(db: Session, dataset_id: int) -> list[int]:
    rows = db.execute(select(Stop).where(Stop.dataset_id == dataset_id, Stop.geocode_status == "FAILED")).scalars().all()
    return [int(row.id) for row in rows]


def _resolve_dataset_input(db: Session, dataset_arg: str) -> tuple[int, dict[str, Any]]:
    if str(dataset_arg).strip().isdigit():
        dataset_id = int(str(dataset_arg).strip())
        dataset = db.get(Dataset, dataset_id)
        if dataset is None:
            raise ValueError(f"Dataset {dataset_id} not found")
        return dataset_id, {
            "input_kind": "dataset_id",
            "source_dataset_id": dataset_id,
            "filename": dataset.filename,
        }

    source_file = Path(dataset_arg).expanduser()
    if not source_file.exists():
        raise FileNotFoundError(f"Dataset input file not found: {source_file}")

    dataset, validation, _ = create_dataset_from_upload(
        db,
        filename=source_file.name,
        content=source_file.read_bytes(),
        exclude_invalid=True,
    )
    geocode_summary = geocode_dataset(db, dataset.id)
    for stop_id in _failed_stop_ids(db, dataset.id):
        stop = db.get(Stop, stop_id)
        if stop is None:
            continue
        try:
            manual_resolve_stop(
                db,
                stop_id=stop_id,
                corrected_address=stop.address,
                corrected_postal_code=stop.postal_code if not stop.address else None,
                lat=None,
                lon=None,
            )
        except Exception:
            continue

    return dataset.id, {
        "input_kind": "csv_path",
        "source_dataset_id": dataset.id,
        "filename": source_file.name,
        "valid_rows_count": int(validation.valid_rows_count),
        "invalid_rows_count": int(validation.invalid_rows_count),
        "geocode_summary": geocode_summary,
    }


def _hhmm_to_minutes(value: str) -> int:
    hours, minutes = str(value).split(":")
    return int(hours) * 60 + int(minutes)


def _minutes_to_hhmm(value: int) -> str:
    clamped = max(0, min(23 * 60 + 59, int(value)))
    hours = clamped // 60
    minutes = clamped % 60
    return f"{hours:02d}:{minutes:02d}"


def _scale_service_time(value: int | None, scale: float) -> int:
    original = max(0, int(value or 0))
    if abs(scale - 1.0) < 1e-9:
        return original
    if original == 0:
        return 0
    return max(1, int(math.ceil(original * scale)))


def _tighten_time_window(tw_start: str | None, tw_end: str | None) -> tuple[str | None, str | None]:
    if not tw_start or not tw_end:
        return tw_start, tw_end

    start_min = _hhmm_to_minutes(tw_start)
    end_min = _hhmm_to_minutes(tw_end)
    if end_min <= start_min:
        return tw_start, tw_end

    width = end_min - start_min
    max_shrink = max(0, width - TIGHTER_WINDOW_MIN_WIDTH_MINUTES)
    total_shrink = min(TIGHTER_WINDOW_TOTAL_SHRINK_MINUTES, max_shrink)
    if total_shrink <= 0:
        return tw_start, tw_end

    shrink_left = total_shrink // 2
    shrink_right = total_shrink - shrink_left
    return _minutes_to_hhmm(start_min + shrink_left), _minutes_to_hhmm(end_min - shrink_right)


def _clone_dataset_for_scenario(db: Session, *, source_dataset_id: int, scenario: SensitivityScenario) -> int:
    source_dataset = db.get(Dataset, source_dataset_id)
    if source_dataset is None:
        raise ValueError(f"Dataset {source_dataset_id} not found")

    source_stops = db.execute(select(Stop).where(Stop.dataset_id == source_dataset_id).order_by(Stop.id.asc())).scalars().all()
    cloned = Dataset(
        filename=f"{source_dataset.filename}__{scenario.scenario_id}",
        status="GEOCODED",
    )
    db.add(cloned)
    db.flush()

    for stop in source_stops:
        tw_start = stop.tw_start
        tw_end = stop.tw_end
        if scenario.time_window_mode == "tighter":
            tw_start, tw_end = _tighten_time_window(stop.tw_start, stop.tw_end)

        db.add(
            Stop(
                dataset_id=cloned.id,
                stop_ref=stop.stop_ref,
                address=stop.address,
                postal_code=stop.postal_code,
                demand=int(stop.demand or 0),
                service_time_min=_scale_service_time(stop.service_time_min, scenario.service_time_scale),
                tw_start=tw_start,
                tw_end=tw_end,
                phone=stop.phone,
                contact_name=stop.contact_name,
                lat=stop.lat,
                lon=stop.lon,
                geocode_status=stop.geocode_status,
                geocode_meta=stop.geocode_meta,
            )
        )

    db.commit()
    return int(cloned.id)


def _default_scenarios() -> list[SensitivityScenario]:
    base = {
        "num_vehicles": 2,
        "vehicle_capacity": 20,
        "workday_start": "08:00",
        "workday_end": "18:00",
        "allow_drop_visits": True,
        "service_time_scale": 1.0,
        "time_window_mode": "original",
    }
    return [
        SensitivityScenario("BASE_CASE", "Nominal base case", "base_case", "nominal", **base),
        SensitivityScenario("FLEET_1", "Fleet size 1", "fleet_size", "1", **{**base, "num_vehicles": 1}),
        SensitivityScenario("FLEET_2", "Fleet size 2", "fleet_size", "2", **base),
        SensitivityScenario("FLEET_3", "Fleet size 3", "fleet_size", "3", **{**base, "num_vehicles": 3}),
        SensitivityScenario("CAPACITY_8", "Capacity 8", "vehicle_capacity", "8", **{**base, "vehicle_capacity": 8}),
        SensitivityScenario("CAPACITY_20", "Capacity 20", "vehicle_capacity", "20", **base),
        SensitivityScenario("CAPACITY_30", "Capacity 30", "vehicle_capacity", "30", **{**base, "vehicle_capacity": 30}),
        SensitivityScenario("WORKDAY_0800_1800", "Workday 08:00-18:00", "workday_duration", "08:00-18:00", **base),
        SensitivityScenario(
            "WORKDAY_0900_1700",
            "Workday 09:00-17:00",
            "workday_duration",
            "09:00-17:00",
            **{**base, "workday_start": "09:00", "workday_end": "17:00"},
        ),
        SensitivityScenario("SERVICE_1_0X", "Service time 1.0x", "service_time_scale", "1.0x", **base),
        SensitivityScenario(
            "SERVICE_1_2X",
            "Service time 1.2x",
            "service_time_scale",
            "1.2x",
            **{**base, "service_time_scale": 1.2},
        ),
        SensitivityScenario("TW_ORIGINAL", "Original time windows", "time_window_tightness", "original", **base),
        SensitivityScenario(
            "TW_TIGHTER",
            "Tighter time windows",
            "time_window_tightness",
            "tighter",
            **{**base, "time_window_mode": "tighter"},
        ),
    ]


def _build_result_row(
    *,
    summary: dict[str, Any],
    scenario: SensitivityScenario,
    travel_time_source: str,
    model_version: str,
    source_dataset_id: int,
    scenario_dataset_id: int,
) -> SensitivityRow:
    return SensitivityRow(
        scenario_id=scenario.scenario_id,
        scenario_label=scenario.scenario_label,
        factor_changed=scenario.factor_changed,
        factor_value=scenario.factor_value,
        travel_time_source=travel_time_source,
        model_version=model_version,
        source_dataset_id=int(source_dataset_id),
        scenario_dataset_id=int(scenario_dataset_id),
        num_vehicles=int(scenario.num_vehicles),
        vehicle_capacity=int(scenario.vehicle_capacity) if scenario.vehicle_capacity is not None else None,
        workday_start=scenario.workday_start,
        workday_end=scenario.workday_end,
        allow_drop_visits=bool(scenario.allow_drop_visits),
        service_time_scale=float(scenario.service_time_scale),
        time_window_mode=scenario.time_window_mode,
        makespan_seconds=float(summary.get("makespan_s") or 0.0),
        total_distance_m=float(summary.get("total_distance_m") or 0.0),
        served_stops=int(summary.get("served_count") or 0),
        total_stops=int(summary.get("total_stops") or 0),
        on_time_rate=float(summary.get("on_time_rate") or 0.0),
        late_stops=int(summary.get("late_stops_count") or 0),
        dropped_stops=int(summary.get("unserved_count") or 0),
        solver_status=str(summary.get("solver_status") or "UNKNOWN"),
        solve_time_seconds=(
            float(summary["solve_time_seconds"])
            if summary.get("solve_time_seconds") is not None
            else None
        ),
        feasible=bool(summary.get("feasible")),
        objective_value=float(summary.get("objective") or 0.0),
        sum_vehicle_duration_seconds=float(summary.get("sum_vehicle_duration_s") or 0.0),
        avg_waiting_seconds=float(summary.get("avg_waiting_s") or 0.0),
    )


def _run_sensitivity_analysis(args: argparse.Namespace) -> dict[str, Any]:
    base_db = Path(args.base_db).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_db = output_dir / "sensitivity_work.db"
    shutil.copyfile(base_db, work_db)

    session_factory = _build_session_factory(work_db)
    scenarios = _default_scenarios()
    result_rows: list[SensitivityRow] = []

    with session_factory() as db:
        _ensure_model_row(db, args.calibrated_model_version)
        source_dataset_id, input_meta = _resolve_dataset_input(db, args.dataset)

        for scenario in scenarios:
            print(f"Running {scenario.scenario_id}...")
            scenario_dataset_id = _clone_dataset_for_scenario(
                db,
                source_dataset_id=source_dataset_id,
                scenario=scenario,
            )
            payload = OptimizationPayload(
                depot_lat=float(args.depot_lat),
                depot_lon=float(args.depot_lon),
                num_vehicles=int(scenario.num_vehicles),
                capacity=int(scenario.vehicle_capacity) if scenario.vehicle_capacity is not None else None,
                workday_start=scenario.workday_start,
                workday_end=scenario.workday_end,
                solver_time_limit_s=int(args.solver_time_limit_s),
                allow_drop_visits=bool(scenario.allow_drop_visits),
                use_live_traffic=False,
            )
            report = run_ab_simulation(
                db,
                dataset_id=scenario_dataset_id,
                payload=payload,
                model_version=args.calibrated_model_version,
            )
            result_rows.append(
                _build_result_row(
                    summary=report["baseline"],
                    scenario=scenario,
                    travel_time_source="fallback_baseline",
                    model_version=str(report.get("baseline_version") or "fallback_v1"),
                    source_dataset_id=source_dataset_id,
                    scenario_dataset_id=scenario_dataset_id,
                )
            )
            result_rows.append(
                _build_result_row(
                    summary=report["ml"],
                    scenario=scenario,
                    travel_time_source="calibrated_ml",
                    model_version=str(report.get("ml_version") or args.calibrated_model_version),
                    source_dataset_id=source_dataset_id,
                    scenario_dataset_id=scenario_dataset_id,
                )
            )

    return {
        "generated_at": date.today().isoformat(),
        "base_db": str(base_db),
        "work_db": str(work_db),
        "dataset_arg": args.dataset,
        "input_meta": input_meta,
        "depot_lat": float(args.depot_lat),
        "depot_lon": float(args.depot_lon),
        "solver_time_limit_s": int(args.solver_time_limit_s),
        "calibrated_model_version": args.calibrated_model_version,
        "time_window_tightening_rule": {
            "mode": "trim_explicit_windows",
            "total_shrink_minutes": TIGHTER_WINDOW_TOTAL_SHRINK_MINUTES,
            "minimum_width_minutes": TIGHTER_WINDOW_MIN_WIDTH_MINUTES,
        },
        "scenarios": [asdict(item) for item in scenarios],
        "rows": [asdict(item) for item in result_rows],
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _base_rows_by_source(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row["travel_time_source"]): row
        for row in rows
        if str(row["scenario_id"]) == "BASE_CASE"
    }


def _paired_rows_by_scenario(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    paired: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        scenario_id = str(row["scenario_id"])
        paired.setdefault(scenario_id, {})
        paired[scenario_id][str(row["travel_time_source"])] = row
    return paired


def _effect_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base_rows = _base_rows_by_source(rows)
    effects: dict[tuple[str, str], dict[str, Any]] = {}

    for row in rows:
        if str(row["scenario_id"]) == "BASE_CASE":
            continue
        source = str(row["travel_time_source"])
        base = base_rows.get(source)
        if base is None:
            continue
        key = (source, str(row["factor_changed"]))
        makespan_delta = float(row["makespan_seconds"]) - float(base["makespan_seconds"])
        existing = effects.get(key)
        if existing is None or abs(makespan_delta) > abs(float(existing["max_abs_makespan_delta_seconds"])):
            effects[key] = {
                "travel_time_source": source,
                "factor_changed": str(row["factor_changed"]),
                "scenario_id": str(row["scenario_id"]),
                "factor_value": str(row["factor_value"]),
                "max_abs_makespan_delta_seconds": float(makespan_delta),
                "max_abs_distance_delta_m": float(row["total_distance_m"]) - float(base["total_distance_m"]),
            }

    return sorted(effects.values(), key=lambda item: (item["travel_time_source"], item["factor_changed"]))


def _calibrated_impact_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    paired = _paired_rows_by_scenario(rows)
    makespan_deltas: list[float] = []
    distance_deltas: list[float] = []
    solve_time_deltas: list[float] = []
    calibrated_makespan_wins = 0
    calibrated_distance_wins = 0

    for variants in paired.values():
        baseline = variants.get("fallback_baseline")
        calibrated = variants.get("calibrated_ml")
        if baseline is None or calibrated is None:
            continue
        makespan_delta = float(calibrated["makespan_seconds"]) - float(baseline["makespan_seconds"])
        distance_delta = float(calibrated["total_distance_m"]) - float(baseline["total_distance_m"])
        makespan_deltas.append(makespan_delta)
        distance_deltas.append(distance_delta)
        if makespan_delta < 0:
            calibrated_makespan_wins += 1
        if distance_delta < 0:
            calibrated_distance_wins += 1
        baseline_solve = baseline.get("solve_time_seconds")
        calibrated_solve = calibrated.get("solve_time_seconds")
        if baseline_solve is not None and calibrated_solve is not None:
            solve_time_deltas.append(float(calibrated_solve) - float(baseline_solve))

    total = len(makespan_deltas)
    return {
        "scenario_pairs": total,
        "calibrated_makespan_wins": calibrated_makespan_wins,
        "calibrated_distance_wins": calibrated_distance_wins,
        "mean_calibrated_minus_fallback_makespan_seconds": mean(makespan_deltas) if makespan_deltas else 0.0,
        "mean_calibrated_minus_fallback_distance_m": mean(distance_deltas) if distance_deltas else 0.0,
        "mean_calibrated_minus_fallback_solve_time_seconds": mean(solve_time_deltas) if solve_time_deltas else None,
    }


def _summary_payload(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload["rows"]
    return {
        "effect_table": _effect_table(rows),
        "calibrated_impact": _calibrated_impact_summary(rows),
    }


def _fmt_optional_float(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.{digits}f}"


def _write_markdown(path: Path, payload: dict[str, Any], summary: dict[str, Any]) -> None:
    rows = payload["rows"]
    effect_rows = summary["effect_table"]
    calibrated_impact = summary["calibrated_impact"]

    lines: list[str] = []
    lines.append("# Sensitivity Analysis Summary")
    lines.append("")
    lines.append(f"Date: {payload['generated_at']}")
    lines.append("")
    lines.append("## Base Case")
    lines.append("")
    lines.append("- Dataset input: `{}`".format(payload["dataset_arg"]))
    lines.append("- Nominal base case: `num_vehicles=2`, `vehicle_capacity=20`, `workday=08:00-18:00`, `allow_drop_visits=true`")
    lines.append("- Stop service times: original dataset values at `1.0x` scale")
    lines.append("- Stop time windows: original dataset values")
    lines.append("- Travel-time variants: `fallback_baseline` and calibrated ML model `{}`".format(payload["calibrated_model_version"]))
    lines.append("- Solver time limit per run: `{}` seconds".format(payload["solver_time_limit_s"]))
    lines.append("- Depot: `({}, {})`".format(payload["depot_lat"], payload["depot_lon"]))
    lines.append("")
    lines.append("## Factors Varied")
    lines.append("")
    lines.append("| Factor | Values |")
    lines.append("| --- | --- |")
    lines.append("| Fleet size | `1`, `2`, `3` vehicles |")
    lines.append("| Vehicle capacity | `8`, `20`, `30` parcels |")
    lines.append("| Workday duration | `08:00-18:00`, `09:00-17:00` |")
    lines.append("| Service time scaling | `1.0x`, `1.2x` |")
    lines.append("| Time-window tightness | `original`, `tighter` |")
    lines.append("| Travel-time source | paired `fallback_baseline` and calibrated ML for every scenario |")
    lines.append("")
    lines.append("## Key Findings")
    lines.append("")
    lines.append("- Calibrated-vs-fallback scenario pairs: `{}`".format(calibrated_impact["scenario_pairs"]))
    lines.append(
        "- Calibrated model improved makespan in `{}/{}` scenario pairs and improved distance in `{}/{}` pairs.".format(
            calibrated_impact["calibrated_makespan_wins"],
            calibrated_impact["scenario_pairs"],
            calibrated_impact["calibrated_distance_wins"],
            calibrated_impact["scenario_pairs"],
        )
    )
    lines.append(
        "- Mean calibrated-minus-fallback makespan delta: `{}` seconds.".format(
            _fmt_optional_float(calibrated_impact["mean_calibrated_minus_fallback_makespan_seconds"])
        )
    )
    lines.append(
        "- Mean calibrated-minus-fallback distance delta: `{}` m.".format(
            _fmt_optional_float(calibrated_impact["mean_calibrated_minus_fallback_distance_m"])
        )
    )
    if calibrated_impact["mean_calibrated_minus_fallback_solve_time_seconds"] is None:
        lines.append("- Solver runtime comparison is reported only where the underlying solver wrapper exposed solve time.")
    else:
        lines.append(
            "- Mean calibrated-minus-fallback solve-time delta: `{}` seconds.".format(
                _fmt_optional_float(calibrated_impact["mean_calibrated_minus_fallback_solve_time_seconds"], digits=3)
            )
        )
    lines.append("")
    lines.append("### Largest Makespan Shifts by Factor")
    lines.append("")
    lines.append("| Travel-time source | Factor | Scenario | Value | Makespan delta vs source base case (s) | Distance delta vs source base case (m) |")
    lines.append("| --- | --- | --- | --- | ---: | ---: |")
    for row in effect_rows:
        lines.append(
            "| {} | {} | {} | {} | {} | {} |".format(
                row["travel_time_source"],
                row["factor_changed"],
                row["scenario_id"],
                row["factor_value"],
                _fmt_optional_float(float(row["max_abs_makespan_delta_seconds"])),
                _fmt_optional_float(float(row["max_abs_distance_delta_m"])),
            )
        )
    lines.append("")
    lines.append("## Scenario Results")
    lines.append("")
    lines.append("| Scenario | Source | Factor | Value | Makespan (s) | Distance (m) | Served | On-time rate | Late | Dropped | Solver status | Solve time (s) |")
    lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |")
    for row in rows:
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {}/{} | {:.2f} | {} | {} | {} | {} |".format(
                row["scenario_id"],
                row["travel_time_source"],
                row["factor_changed"],
                row["factor_value"],
                _fmt_optional_float(float(row["makespan_seconds"])),
                _fmt_optional_float(float(row["total_distance_m"])),
                int(row["served_stops"]),
                int(row["total_stops"]),
                float(row["on_time_rate"]),
                int(row["late_stops"]),
                int(row["dropped_stops"]),
                row["solver_status"],
                _fmt_optional_float(row["solve_time_seconds"], digits=3),
            )
        )
    lines.append("")
    lines.append("## Limitations and Assumptions")
    lines.append("")
    lines.append("- Service-time scaling was applied by editing copied stop rows in an isolated work database; the source dataset was not modified.")
    lines.append(
        "- The `tighter` time-window mode trims explicit stop windows by {} minutes in total while preserving at least {} minutes of width; stops without explicit time windows are left unchanged.".format(
            payload["time_window_tightening_rule"]["total_shrink_minutes"],
            payload["time_window_tightening_rule"]["minimum_width_minutes"],
        )
    )
    lines.append("- Travel-time source was evaluated as paired fallback-versus-calibrated runs under the same operational settings.")
    lines.append("- `solve_time_seconds` measures the OR-Tools solver call only. Matrix building and prediction time are not included in that field.")
    lines.append("- `late_stops` and `dropped_stops` are limited to what the existing VRPTW evaluation path exposes.")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _svg_text(
    x: float,
    y: float,
    content: str,
    *,
    size: int = 18,
    weight: str = "400",
    fill: str = SVG_INK,
    anchor: str = "start",
    family: str = "Arial",
) -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{escape(content)}</text>'
    )


def _svg_rect(x: float, y: float, width: float, height: float, fill: str, *, rx: float = 0) -> str:
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{fill}" rx="{rx}" ry="{rx}" />'


def _svg_line(x1: float, y1: float, x2: float, y2: float, *, stroke: str = SVG_AXIS, stroke_width: float = 1) -> str:
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{stroke_width}" />'


def _write_svg(path: Path, title: str, body: list[str]) -> None:
    content = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_WIDTH}" height="{SVG_HEIGHT}" viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}">',
        f"<title>{escape(title)}</title>",
        _svg_rect(0, 0, SVG_WIDTH, SVG_HEIGHT, SVG_BG),
        *body,
        "</svg>",
    ]
    path.write_text("\n".join(content), encoding="utf-8")


def _chart_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paired = _paired_rows_by_scenario(rows)
    ordered = []
    for scenario in _default_scenarios():
        variants = paired.get(scenario.scenario_id, {})
        baseline = variants.get("fallback_baseline")
        calibrated = variants.get("calibrated_ml")
        if baseline is None or calibrated is None:
            continue
        ordered.append(
            {
                "scenario_id": scenario.scenario_id,
                "label": scenario.scenario_label,
                "fallback_makespan": float(baseline["makespan_seconds"]),
                "calibrated_makespan": float(calibrated["makespan_seconds"]),
                "fallback_distance": float(baseline["total_distance_m"]),
                "calibrated_distance": float(calibrated["total_distance_m"]),
            }
        )
    return ordered


def _grouped_bar_chart(
    *,
    path: Path,
    title: str,
    subtitle: str,
    y_label: str,
    rows: list[dict[str, Any]],
    fallback_key: str,
    calibrated_key: str,
) -> None:
    plot = PlotArea(left=110, top=170, right=1330, bottom=710)
    max_value = max(
        max(float(row[fallback_key]), float(row[calibrated_key]))
        for row in rows
    ) if rows else 1.0
    step = max(1.0, math.ceil(max_value / 5))
    y_max = step * 5

    body = [
        _svg_text(80, 70, title, size=34, weight="700", family="Georgia"),
        _svg_text(80, 104, subtitle, size=18, fill="#41505A"),
        _svg_line(80, 124, SVG_WIDTH - 80, 124, stroke="#BDB6A8", stroke_width=2),
        _svg_rect(970, 74, 18, 18, SVG_FALLBACK, rx=4),
        _svg_text(998, 89, "Fallback baseline", size=16, fill="#33434D"),
        _svg_rect(1170, 74, 18, 18, SVG_CALIBRATED, rx=4),
        _svg_text(1198, 89, "Calibrated ML", size=16, fill="#33434D"),
    ]

    for tick in range(6):
        value = tick * step
        y = plot.bottom - (value / y_max) * plot.height
        body.append(_svg_line(plot.left, y, plot.right, y, stroke=SVG_GRID, stroke_width=1))
        body.append(_svg_text(plot.left - 16, y + 6, f"{int(value):,}", size=15, anchor="end", fill="#54636C"))

    body.append(_svg_line(plot.left, plot.top, plot.left, plot.bottom, stroke=SVG_AXIS, stroke_width=2))
    body.append(_svg_line(plot.left, plot.bottom, plot.right, plot.bottom, stroke=SVG_AXIS, stroke_width=2))
    body.append(_svg_text(48, 442, y_label, size=16, fill="#54636C"))

    if rows:
        group_width = plot.width / len(rows)
        bar_width = group_width * 0.24
        for index, row in enumerate(rows):
            center_x = plot.left + group_width * index + group_width / 2
            body.append(_svg_text(center_x, plot.bottom + 34, row["scenario_id"], size=14, weight="700", anchor="middle"))

            fallback_value = float(row[fallback_key])
            fallback_height = (fallback_value / y_max) * plot.height
            fallback_x = center_x - bar_width - 6
            fallback_y = plot.bottom - fallback_height
            body.append(_svg_rect(fallback_x, fallback_y, bar_width, fallback_height, SVG_FALLBACK, rx=6))

            calibrated_value = float(row[calibrated_key])
            calibrated_height = (calibrated_value / y_max) * plot.height
            calibrated_x = center_x + 6
            calibrated_y = plot.bottom - calibrated_height
            body.append(_svg_rect(calibrated_x, calibrated_y, bar_width, calibrated_height, SVG_CALIBRATED, rx=6))

    _write_svg(path, title, body)


def _write_plots(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    chart_rows = _chart_rows(rows)
    _grouped_bar_chart(
        path=output_dir / "sensitivity_makespan_by_scenario.svg",
        title="Sensitivity Analysis Makespan by Scenario",
        subtitle="Paired fallback-versus-calibrated reruns under one-factor-at-a-time scenario changes.",
        y_label="Makespan (s)",
        rows=chart_rows,
        fallback_key="fallback_makespan",
        calibrated_key="calibrated_makespan",
    )
    _grouped_bar_chart(
        path=output_dir / "sensitivity_distance_by_scenario.svg",
        title="Sensitivity Analysis Distance by Scenario",
        subtitle="Total distance by scenario for fallback baseline and calibrated ML travel-time sources.",
        y_label="Distance (m)",
        rows=chart_rows,
        fallback_key="fallback_distance",
        calibrated_key="calibrated_distance",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one-factor-at-a-time sensitivity analysis for SG Route OPT.")
    parser.add_argument("--dataset", required=True, help="Dataset ID in the DB or a path to an input CSV/XLSX file.")
    parser.add_argument("--base-db", default=str(BACKEND_DIR / "app.db"))
    parser.add_argument("--output-dir", default=str(BACKEND_DIR / "ch6_outputs" / f"sensitivity_{date.today().isoformat()}"))
    parser.add_argument("--calibrated-model-version", default=DEFAULT_CALIBRATED_MODEL_VERSION)
    parser.add_argument("--depot-lat", type=float, default=DEFAULT_DEPOT_LAT)
    parser.add_argument("--depot-lon", type=float, default=DEFAULT_DEPOT_LON)
    parser.add_argument("--solver-time-limit-s", type=int, default=DEFAULT_SOLVER_TIME_LIMIT_S)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = _run_sensitivity_analysis(args)
    summary = _summary_payload(payload)

    output_dir = Path(args.output_dir).resolve()
    csv_path = output_dir / "sensitivity_results.csv"
    markdown_path = output_dir / "sensitivity_summary.md"
    raw_json_path = output_dir / "sensitivity_results.json"

    _write_csv(csv_path, payload["rows"])
    _write_markdown(markdown_path, payload, summary)
    _write_plots(output_dir, payload["rows"])
    raw_json_path.write_text(json.dumps({"summary": summary, "raw": payload}, indent=2), encoding="utf-8")

    print(csv_path)
    print(markdown_path)
    print(raw_json_path)
    print(output_dir / "sensitivity_makespan_by_scenario.svg")
    print(output_dir / "sensitivity_distance_by_scenario.svg")


if __name__ == "__main__":
    main()
