from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

ARTIFACT_DIR = ROOT / "backend" / "app" / "ml" / "artifacts"

INITIAL_MODEL_VERSION = "v20260315045420274714"
CALIBRATED_MODEL_VERSION = "v20260315063821017757"

DATASET_FILES = [Path(r"C:/Users/User/Downloads") / f"stops_experiment_{i}.csv" for i in range(1, 11)]

SCENARIOS = [
    {
        "id": "S1",
        "label": "Nominal",
        "num_vehicles": 2,
        "capacity": 20,
        "workday_start": "08:00",
        "workday_end": "18:00",
        "allow_drop_visits": True,
    },
    {
        "id": "S2",
        "label": "Single vehicle",
        "num_vehicles": 1,
        "capacity": 20,
        "workday_start": "08:00",
        "workday_end": "18:00",
        "allow_drop_visits": True,
    },
    {
        "id": "S3",
        "label": "Tight capacity",
        "num_vehicles": 2,
        "capacity": 8,
        "workday_start": "08:00",
        "workday_end": "18:00",
        "allow_drop_visits": True,
    },
    {
        "id": "S4",
        "label": "Shorter workday",
        "num_vehicles": 2,
        "capacity": 20,
        "workday_start": "09:00",
        "workday_end": "17:00",
        "allow_drop_visits": True,
    },
    {
        "id": "S5",
        "label": "No-drop variant",
        "num_vehicles": 2,
        "capacity": 20,
        "workday_start": "08:00",
        "workday_end": "18:00",
        "allow_drop_visits": False,
    },
]


@dataclass
class DatasetRunSummary:
    file_name: str
    dataset_id: int
    stop_count: int
    total_demand: int
    total_service_min: int
    geocode_success_count: int
    geocode_failed_count: int
    geocode_sources: dict[str, int]


def _build_session_factory(db_path: Path) -> sessionmaker[Session]:
    db_url = f"sqlite:///{db_path.resolve().as_posix()}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False, "timeout": 30}, future=True)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _ensure_model_row(db: Session, version: str) -> None:
    from app.models import MLModel

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


def _geocode_sources(db: Session, dataset_id: int) -> dict[str, int]:
    from app.models import Stop

    rows = db.execute(select(Stop).where(Stop.dataset_id == dataset_id)).scalars().all()
    counts: Counter[str] = Counter()
    for row in rows:
        source = "unknown"
        if row.geocode_meta:
            try:
                payload = json.loads(row.geocode_meta)
                source = str(payload.get("source") or source)
            except json.JSONDecodeError:
                source = "invalid_json"
        counts[source] += 1
    return dict(sorted(counts.items()))


def _dataset_stats(db: Session, dataset_id: int) -> tuple[int, int]:
    from app.models import Stop

    rows = db.execute(select(Stop).where(Stop.dataset_id == dataset_id)).scalars().all()
    total_demand = sum(int(row.demand or 0) for row in rows)
    total_service_min = sum(int(row.service_time_min or 0) for row in rows)
    return total_demand, total_service_min


def _failed_stop_ids(db: Session, dataset_id: int) -> list[int]:
    from app.models import Stop

    rows = db.execute(select(Stop).where(Stop.dataset_id == dataset_id, Stop.geocode_status == "FAILED")).scalars().all()
    return [int(row.id) for row in rows]


def _geocode_totals(db: Session, dataset_id: int) -> tuple[int, int]:
    from app.models import Stop

    rows = db.execute(select(Stop).where(Stop.dataset_id == dataset_id)).scalars().all()
    success = sum(1 for row in rows if row.geocode_status in {"SUCCESS", "MANUAL"})
    failed = sum(1 for row in rows if row.geocode_status == "FAILED")
    return success, failed


def _comparison_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["key"]): row for row in report.get("comparison", [])}


def _run_eval(args: argparse.Namespace) -> dict[str, Any]:
    from app.services.datasets import create_dataset_from_upload
    from app.services.geocoding import geocode_dataset
    from app.services.geocoding import manual_resolve_stop
    from app.services.onemap_client import get_onemap_client
    from app.services.optimization import OptimizationPayload
    from app.services.optimization_experiments import run_ab_simulation

    base_db = Path(args.base_db)
    work_db = Path(args.work_db)
    if args.reset_db or not work_db.exists():
        shutil.copyfile(base_db, work_db)

    SessionFactory = _build_session_factory(work_db)

    dataset_runs: list[DatasetRunSummary] = []
    scenario_results: list[dict[str, Any]] = []

    onemap_mock_mode = bool(get_onemap_client().mock_mode)

    with SessionFactory() as db:
        _ensure_model_row(db, INITIAL_MODEL_VERSION)
        _ensure_model_row(db, CALIBRATED_MODEL_VERSION)

        selected_scenarios = [item for item in SCENARIOS if item["id"] in args.scenario_ids]

        for source_file in DATASET_FILES:
            print(f"Importing {source_file.name}...")
            content = source_file.read_bytes()
            dataset, validation, _ = create_dataset_from_upload(
                db,
                filename=source_file.name,
                content=content,
                exclude_invalid=True,
            )
            geocode_dataset(db, dataset.id)
            for stop_id in _failed_stop_ids(db, dataset.id):
                try:
                    from app.models import Stop

                    stop = db.get(Stop, stop_id)
                    if stop is None:
                        continue
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
            total_demand, total_service_min = _dataset_stats(db, dataset.id)
            geocode_success_count, geocode_failed_count = _geocode_totals(db, dataset.id)
            dataset_runs.append(
                DatasetRunSummary(
                    file_name=source_file.name,
                    dataset_id=dataset.id,
                    stop_count=validation.valid_rows_count,
                    total_demand=total_demand,
                    total_service_min=total_service_min,
                    geocode_success_count=geocode_success_count,
                    geocode_failed_count=geocode_failed_count,
                    geocode_sources=_geocode_sources(db, dataset.id),
                )
            )

            for scenario in selected_scenarios:
                print(f"Running {source_file.name} {scenario['id']}...")
                payload = OptimizationPayload(
                    depot_lat=1.3521,
                    depot_lon=103.8198,
                    num_vehicles=int(scenario["num_vehicles"]),
                    capacity=int(scenario["capacity"]),
                    workday_start=str(scenario["workday_start"]),
                    workday_end=str(scenario["workday_end"]),
                    solver_time_limit_s=int(args.solver_time_limit_s),
                    allow_drop_visits=bool(scenario["allow_drop_visits"]),
                    use_live_traffic=False,
                )
                initial_report = run_ab_simulation(db, dataset_id=dataset.id, payload=payload, model_version=INITIAL_MODEL_VERSION)
                calibrated_report = run_ab_simulation(db, dataset_id=dataset.id, payload=payload, model_version=CALIBRATED_MODEL_VERSION)

                initial_cmp = _comparison_map(initial_report)
                calibrated_cmp = _comparison_map(calibrated_report)

                scenario_results.append(
                    {
                        "file_name": source_file.name,
                        "dataset_id": dataset.id,
                        "scenario": dict(scenario),
                        "baseline_version": initial_report.get("baseline_version"),
                        "routing_note": (
                            "onemap_client.mock_mode=true_without_credentials"
                            if onemap_mock_mode
                            else "authenticated_onemap_routing_enabled"
                        ),
                        "initial_model": {
                            "version": INITIAL_MODEL_VERSION,
                            "report": initial_report,
                            "kpis": {
                                "makespan_s": initial_cmp["makespan_s"],
                                "total_distance_m": initial_cmp["total_distance_m"],
                                "sum_vehicle_duration_s": initial_cmp["sum_vehicle_duration_s"],
                                "served_ratio": initial_cmp["served_ratio"],
                                "on_time_rate": initial_cmp["on_time_rate"],
                                "unserved_count": initial_cmp["unserved_count"],
                            },
                        },
                        "calibrated_model": {
                            "version": CALIBRATED_MODEL_VERSION,
                            "report": calibrated_report,
                            "kpis": {
                                "makespan_s": calibrated_cmp["makespan_s"],
                                "total_distance_m": calibrated_cmp["total_distance_m"],
                                "sum_vehicle_duration_s": calibrated_cmp["sum_vehicle_duration_s"],
                                "served_ratio": calibrated_cmp["served_ratio"],
                                "on_time_rate": calibrated_cmp["on_time_rate"],
                                "unserved_count": calibrated_cmp["unserved_count"],
                            },
                        },
                    }
                )

        return {
            "generated_at": date.today().isoformat(),
            "base_db": str(base_db),
            "work_db": str(work_db),
            "solver_time_limit_s": int(args.solver_time_limit_s),
            "scenario_ids": list(args.scenario_ids),
            "geocode_mock_mode": onemap_mock_mode,
            "dataset_runs": [asdict(item) for item in dataset_runs],
            "scenario_results": scenario_results,
        }


def _aggregate_results(payload: dict[str, Any]) -> dict[str, Any]:
    by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    nominal_rows: list[dict[str, Any]] = []

    for row in payload["scenario_results"]:
        scenario_id = str(row["scenario"]["id"])
        by_scenario[scenario_id].append(row)
        if scenario_id == "S1":
            nominal_rows.append(row)

    scenario_summary: list[dict[str, Any]] = []
    for scenario_id, rows in by_scenario.items():
        initial_makespan = [float(item["initial_model"]["kpis"]["makespan_s"]["improvement_pct"]) for item in rows]
        calibrated_makespan = [float(item["calibrated_model"]["kpis"]["makespan_s"]["improvement_pct"]) for item in rows]
        initial_distance = [float(item["initial_model"]["kpis"]["total_distance_m"]["improvement_pct"]) for item in rows]
        calibrated_distance = [float(item["calibrated_model"]["kpis"]["total_distance_m"]["improvement_pct"]) for item in rows]

        scenario_summary.append(
            {
                "scenario_id": scenario_id,
                "label": rows[0]["scenario"]["label"],
                "dataset_count": len(rows),
                "initial_mean_makespan_improvement_pct": mean(initial_makespan),
                "initial_positive_count": sum(1 for value in initial_makespan if value > 0),
                "initial_non_positive_count": sum(1 for value in initial_makespan if value <= 0),
                "calibrated_mean_makespan_improvement_pct": mean(calibrated_makespan),
                "calibrated_positive_count": sum(1 for value in calibrated_makespan if value > 0),
                "calibrated_non_positive_count": sum(1 for value in calibrated_makespan if value <= 0),
                "initial_mean_distance_improvement_pct": mean(initial_distance),
                "calibrated_mean_distance_improvement_pct": mean(calibrated_distance),
            }
        )

    nominal_summary = [
        {
            "file_name": row["file_name"],
            "dataset_id": row["dataset_id"],
            "baseline_makespan_s": row["initial_model"]["report"]["baseline"]["makespan_s"],
            "initial_makespan_improvement_pct": row["initial_model"]["kpis"]["makespan_s"]["improvement_pct"],
            "calibrated_makespan_improvement_pct": row["calibrated_model"]["kpis"]["makespan_s"]["improvement_pct"],
            "baseline_distance_m": row["initial_model"]["report"]["baseline"]["total_distance_m"],
            "initial_distance_improvement_pct": row["initial_model"]["kpis"]["total_distance_m"]["improvement_pct"],
            "calibrated_distance_improvement_pct": row["calibrated_model"]["kpis"]["total_distance_m"]["improvement_pct"],
        }
        for row in nominal_rows
    ]

    return {
        "scenario_summary": sorted(scenario_summary, key=lambda item: item["scenario_id"]),
        "nominal_summary": nominal_summary,
    }


def _write_markdown(path: Path, payload: dict[str, Any], aggregates: dict[str, Any]) -> None:
    dataset_runs = payload["dataset_runs"]
    scenario_summary = aggregates["scenario_summary"]
    nominal_summary = aggregates["nominal_summary"]

    lines: list[str] = []
    lines.append("# Chapter 6 New Dataset Evaluation Summary")
    lines.append("")
    lines.append(f"Date: {payload['generated_at']}")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append(f"- Base DB clone source: `{payload['base_db']}`")
    lines.append(f"- Work DB used for this run: `{payload['work_db']}`")
    lines.append(f"- New input files evaluated: `{len(dataset_runs)}`")
    lines.append(f"- Solver time limit per run: `{payload['solver_time_limit_s']}` seconds")
    lines.append(f"- Scenario IDs executed: `{', '.join(payload['scenario_ids'])}`")
    lines.append(f"- OneMap credential mock mode: `{payload['geocode_mock_mode']}`")
    if payload["geocode_mock_mode"]:
        lines.append("- Important limitation: without local OneMap credentials, routing base durations come from the repo's mock route fallback rather than authenticated OneMap routing.")
    else:
        lines.append("- Authenticated OneMap routing was available for this run, so route durations were derived from live OneMap routing responses rather than the repo's mock fallback path.")
    lines.append("")
    lines.append("## Dataset Import and Geocoding")
    lines.append("")
    lines.append("| File | Dataset ID | Stops | Total demand | Total service min | Geocode success | Geocode failed | Geocode sources |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for row in dataset_runs:
        source_text = ", ".join(f"{key}={value}" for key, value in row["geocode_sources"].items())
        lines.append(
            f"| `{row['file_name']}` | {row['dataset_id']} | {row['stop_count']} | {row['total_demand']} | {row['total_service_min']} | {row['geocode_success_count']} | {row['geocode_failed_count']} | {source_text} |"
        )
    lines.append("")
    lines.append("## Aggregate Scenario Results")
    lines.append("")
    lines.append("| Scenario | Datasets | Initial mean makespan improvement | Initial wins | Calibrated mean makespan improvement | Calibrated wins | Initial mean distance improvement | Calibrated mean distance improvement |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in scenario_summary:
        lines.append(
            f"| {row['scenario_id']} {row['label']} | {row['dataset_count']} | {row['initial_mean_makespan_improvement_pct']:+.2f}% | {row['initial_positive_count']}/{row['dataset_count']} | "
            f"{row['calibrated_mean_makespan_improvement_pct']:+.2f}% | {row['calibrated_positive_count']}/{row['dataset_count']} | "
            f"{row['initial_mean_distance_improvement_pct']:+.2f}% | {row['calibrated_mean_distance_improvement_pct']:+.2f}% |"
        )
    lines.append("")
    lines.append("## Nominal Scenario Detail")
    lines.append("")
    lines.append("| File | Dataset ID | Baseline makespan (s) | Initial makespan improvement | Calibrated makespan improvement | Baseline distance (m) | Initial distance improvement | Calibrated distance improvement |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in nominal_summary:
        lines.append(
            f"| `{row['file_name']}` | {row['dataset_id']} | {row['baseline_makespan_s']:.0f} | {float(row['initial_makespan_improvement_pct']):+.2f}% | "
            f"{float(row['calibrated_makespan_improvement_pct']):+.2f}% | {row['baseline_distance_m']:.2f} | "
            f"{float(row['initial_distance_improvement_pct']):+.2f}% | {float(row['calibrated_distance_improvement_pct']):+.2f}% |"
        )
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    if payload["geocode_mock_mode"]:
        lines.append("- These 10 datasets expand the local rerun set, but they are weaker evidence than the earlier OD-cache-backed Dataset 3 study because authenticated OneMap routing was not available in this workspace.")
    else:
        lines.append("- These 10 datasets expand the local rerun set under authenticated OneMap routing, but they are still a separate evidence tier from the earlier OD-cache-backed Dataset 3 study because they rely on newly imported local CSV datasets rather than the original cache-backed evaluation set.")
    lines.append("- The critical question for this run is not absolute field realism but relative sensitivity: whether the harmful original local model still underperforms the fallback baseline, and whether the calibrated model remains directionally better.")
    lines.append("- Use this file together with the JSON output for exact per-dataset, per-scenario results.")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Chapter 6 local evaluation on the 10 new stop datasets.")
    parser.add_argument("--base-db", default="backend/ch6_retrain_eval.db")
    parser.add_argument("--work-db", default="backend/ch6_experiments_10_eval.db")
    parser.add_argument("--reset-db", action="store_true")
    parser.add_argument("--solver-time-limit-s", type=int, default=8)
    parser.add_argument("--scenario-ids", default="S1")
    args = parser.parse_args()
    args.scenario_ids = [item.strip() for item in str(args.scenario_ids).split(",") if item.strip()]
    valid_ids = {item["id"] for item in SCENARIOS}
    unknown = [item for item in args.scenario_ids if item not in valid_ids]
    if unknown:
        raise SystemExit(f"Unknown scenario ids: {', '.join(unknown)}")
    return args


def main() -> None:
    args = parse_args()
    payload = _run_eval(args)
    aggregates = _aggregate_results(payload)

    stamp = date.today().isoformat()
    out_dir = ROOT / "backend" / "ch6_outputs"
    json_path = out_dir / f"ch6_new_datasets_evaluation_{stamp}.json"
    md_path = out_dir / f"ch6_new_datasets_evaluation_{stamp}.md"

    json_path.write_text(json.dumps({"summary": aggregates, "raw": payload}, indent=2), encoding="utf-8")
    _write_markdown(md_path, payload, aggregates)

    print(md_path)
    print(json_path)


if __name__ == "__main__":
    main()
