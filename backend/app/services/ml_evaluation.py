from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActualTravelTime
from app.services.ml_engine import get_ml_engine

REPORT_DIR = Path(__file__).resolve().parents[1] / "cache" / "ml_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    p = math.pi / 180
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _safe_mape(y_true: list[float], y_pred: list[float]) -> float:
    pairs = [(a, p) for a, p in zip(y_true, y_pred) if abs(a) > 1e-9]
    if not pairs:
        return 0.0
    return float(sum(abs((p - a) / a) for a, p in pairs) / len(pairs))


def _pctl(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    arr = sorted(values)
    idx = int(round((len(arr) - 1) * q))
    idx = max(0, min(len(arr) - 1, idx))
    return float(arr[idx])


def _improvement_pct(baseline: float, model: float, *, higher_is_better: bool) -> float | None:
    if abs(baseline) < 1e-9:
        return None
    if higher_is_better:
        return float(((model - baseline) / abs(baseline)) * 100.0)
    return float(((baseline - model) / abs(baseline)) * 100.0)


def _calc_metrics(y_true: list[float], y_pred: list[float]) -> dict[str, float]:
    if not y_true:
        return {
            "mae_s": 0.0,
            "mape_pct": 0.0,
            "rmse_s": 0.0,
            "p90_abs_error_s": 0.0,
            "bias_s": 0.0,
            "within_15pct_rate": 0.0,
        }

    errors = [p - a for a, p in zip(y_true, y_pred)]
    abs_errors = [abs(v) for v in errors]
    mae = _mean(abs_errors)
    mape = _safe_mape(y_true, y_pred) * 100.0
    rmse = math.sqrt(_mean([e * e for e in errors]))
    p90 = _pctl(abs_errors, 0.9)
    bias = _mean(errors)
    within_15 = _mean([1.0 if abs((p - a) / max(a, 1e-9)) <= 0.15 else 0.0 for a, p in zip(y_true, y_pred)])
    return {
        "mae_s": float(mae),
        "mape_pct": float(mape),
        "rmse_s": float(rmse),
        "p90_abs_error_s": float(p90),
        "bias_s": float(bias),
        "within_15pct_rate": float(within_15),
    }


def compare_baseline_vs_model(
    db: Session,
    *,
    days: int = 30,
    limit: int = 5000,
    model_version: str | None = None,
) -> dict[str, Any]:
    start_ts = datetime.utcnow() - timedelta(days=max(1, int(days)))
    rows = db.execute(
        select(ActualTravelTime)
        .where(ActualTravelTime.created_at >= start_ts)
        .order_by(ActualTravelTime.created_at.desc())
        .limit(max(100, int(limit)))
    ).scalars().all()
    if not rows:
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "samples": 0,
            "model_version": model_version,
            "kpis": [],
            "segments": [],
            "note": "No actual travel-time records found in selected window.",
        }

    engine = get_ml_engine()
    sample_rows: list[dict[str, Any]] = []
    y_true: list[float] = []
    y_baseline: list[float] = []
    y_model: list[float] = []
    segment_records: list[dict[str, Any]] = []
    selected_model_version = model_version

    for row in rows:
        try:
            depart_dt = datetime.fromisoformat(row.timestamp_iso)
        except ValueError:
            continue
        distance_m = _haversine_m(row.origin_lat, row.origin_lon, row.dest_lat, row.dest_lon)
        base_duration_s = max(30.0, distance_m / 9.0)

        baseline_pred = engine.predict_duration(
            db,
            od_cache_id=-1,
            base_duration_s=base_duration_s,
            distance_m=distance_m,
            depart_dt=depart_dt,
            origin_lat=row.origin_lat,
            origin_lon=row.origin_lon,
            dest_lat=row.dest_lat,
            dest_lon=row.dest_lon,
            strategy="fallback",
            log_prediction=False,
        )
        model_pred = engine.predict_duration(
            db,
            od_cache_id=-1,
            base_duration_s=base_duration_s,
            distance_m=distance_m,
            depart_dt=depart_dt,
            origin_lat=row.origin_lat,
            origin_lon=row.origin_lon,
            dest_lat=row.dest_lat,
            dest_lon=row.dest_lon,
            strategy="model",
            force_model_version=model_version,
            log_prediction=False,
        )
        if selected_model_version is None and model_pred.model_version != "fallback_v1":
            selected_model_version = model_pred.model_version

        actual = float(row.actual_duration_s)
        y_true.append(actual)
        y_baseline.append(float(baseline_pred.duration_s))
        y_model.append(float(model_pred.duration_s))

        period = "peak" if depart_dt.hour in {7, 8, 9, 17, 18, 19, 20} else "off_peak"
        trip = "short_haul" if distance_m < 5000 else "long_haul"
        segment_records.append(
            {
                "segment_period": period,
                "segment_trip": trip,
                "actual": actual,
                "baseline": float(baseline_pred.duration_s),
                "model": float(model_pred.duration_s),
            }
        )

        if len(sample_rows) < 800:
            sample_rows.append(
                {
                    "timestamp_iso": row.timestamp_iso,
                    "origin_lat": row.origin_lat,
                    "origin_lon": row.origin_lon,
                    "dest_lat": row.dest_lat,
                    "dest_lon": row.dest_lon,
                    "distance_m": round(distance_m, 2),
                    "base_duration_s": round(base_duration_s, 2),
                    "actual_duration_s": round(actual, 2),
                    "baseline_duration_s": round(float(baseline_pred.duration_s), 2),
                    "model_duration_s": round(float(model_pred.duration_s), 2),
                    "model_lower_s": round(float(model_pred.lower_s), 2),
                    "model_upper_s": round(float(model_pred.upper_s), 2),
                }
            )

    baseline_metrics = _calc_metrics(y_true, y_baseline)
    model_metrics = _calc_metrics(y_true, y_model)

    kpi_rows = [
        ("mae_s", "MAE (s)", False),
        ("mape_pct", "MAPE (%)", False),
        ("rmse_s", "RMSE (s)", False),
        ("p90_abs_error_s", "P90 Abs Error (s)", False),
        ("within_15pct_rate", "Within 15% Error Rate", True),
    ]
    kpis = []
    for key, label, higher_better in kpi_rows:
        b = float(baseline_metrics[key])
        m = float(model_metrics[key])
        kpis.append(
            {
                "key": key,
                "label": label,
                "higher_is_better": higher_better,
                "baseline": b,
                "model": m,
                "improvement_pct": _improvement_pct(b, m, higher_is_better=higher_better),
            }
        )

    grouped: dict[tuple[str, str], dict[str, list[float]]] = {}
    for row in segment_records:
        key = (row["segment_period"], row["segment_trip"])
        grouped.setdefault(key, {"actual": [], "baseline": [], "model": []})
        grouped[key]["actual"].append(row["actual"])
        grouped[key]["baseline"].append(row["baseline"])
        grouped[key]["model"].append(row["model"])

    segments = []
    for key, values in grouped.items():
        base_m = _calc_metrics(values["actual"], values["baseline"])
        model_m = _calc_metrics(values["actual"], values["model"])
        segments.append(
            {
                "segment": f"{key[0]}_{key[1]}",
                "count": len(values["actual"]),
                "baseline_mae_s": base_m["mae_s"],
                "model_mae_s": model_m["mae_s"],
                "baseline_mape_pct": base_m["mape_pct"],
                "model_mape_pct": model_m["mape_pct"],
                "mae_improvement_pct": _improvement_pct(base_m["mae_s"], model_m["mae_s"], higher_is_better=False),
            }
        )

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "samples": len(y_true),
        "model_version": selected_model_version or "fallback_v1",
        "baseline_version": "fallback_v1",
        "kpis": kpis,
        "baseline_metrics": baseline_metrics,
        "model_metrics": model_metrics,
        "segments": sorted(segments, key=lambda item: item["segment"]),
        "sample_rows": sample_rows,
    }


def _draw_kpi_plot_png(kpis: list[dict[str, Any]]) -> bytes:
    width, height = 1200, 700
    img = Image.new("RGB", (width, height), (248, 250, 252))
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 40, width - 40, height - 40), outline=(210, 218, 227), fill=(255, 255, 255), width=2)
    draw.text((60, 60), "Baseline vs ML KPI Comparison", fill=(17, 24, 39))

    chart_left = 80
    chart_top = 120
    chart_right = width - 80
    chart_bottom = height - 80
    draw.line((chart_left, chart_bottom, chart_right, chart_bottom), fill=(148, 163, 184), width=2)

    plot_kpis = [k for k in kpis if k["key"] in {"mae_s", "mape_pct", "rmse_s", "p90_abs_error_s"}]
    if not plot_kpis:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    max_value = max(max(float(k["baseline"]), float(k["model"])) for k in plot_kpis)
    max_value = max(1.0, max_value)
    group_w = (chart_right - chart_left) / max(1, len(plot_kpis))

    for idx, row in enumerate(plot_kpis):
        gx = chart_left + idx * group_w
        bar_w = group_w * 0.25
        baseline_h = (float(row["baseline"]) / max_value) * (chart_bottom - chart_top)
        model_h = (float(row["model"]) / max_value) * (chart_bottom - chart_top)

        bx1 = gx + group_w * 0.2
        bx2 = bx1 + bar_w
        mx1 = gx + group_w * 0.55
        mx2 = mx1 + bar_w

        draw.rectangle((bx1, chart_bottom - baseline_h, bx2, chart_bottom), fill=(100, 116, 139))
        draw.rectangle((mx1, chart_bottom - model_h, mx2, chart_bottom), fill=(16, 152, 105))

        draw.text((gx + group_w * 0.15, chart_bottom + 8), row["label"], fill=(51, 65, 85))

    draw.rectangle((chart_right - 260, chart_top + 10, chart_right - 20, chart_top + 70), outline=(203, 213, 225), fill=(255, 255, 255))
    draw.rectangle((chart_right - 245, chart_top + 25, chart_right - 225, chart_top + 45), fill=(100, 116, 139))
    draw.text((chart_right - 215, chart_top + 24), "Baseline", fill=(17, 24, 39))
    draw.rectangle((chart_right - 245, chart_top + 50, chart_right - 225, chart_top + 70), fill=(16, 152, 105))
    draw.text((chart_right - 215, chart_top + 49), "ML Model", fill=(17, 24, 39))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_evaluation_report_zip(report: dict[str, Any]) -> bytes:
    summary_csv = io.StringIO()
    writer = csv.writer(summary_csv)
    writer.writerow(["kpi_key", "kpi_label", "baseline", "model", "improvement_pct", "higher_is_better"])
    for row in report.get("kpis", []):
        writer.writerow(
            [
                row.get("key"),
                row.get("label"),
                row.get("baseline"),
                row.get("model"),
                row.get("improvement_pct"),
                row.get("higher_is_better"),
            ]
        )

    segments_csv = io.StringIO()
    writer = csv.writer(segments_csv)
    writer.writerow(["segment", "count", "baseline_mae_s", "model_mae_s", "baseline_mape_pct", "model_mape_pct", "mae_improvement_pct"])
    for row in report.get("segments", []):
        writer.writerow(
            [
                row.get("segment"),
                row.get("count"),
                row.get("baseline_mae_s"),
                row.get("model_mae_s"),
                row.get("baseline_mape_pct"),
                row.get("model_mape_pct"),
                row.get("mae_improvement_pct"),
            ]
        )

    sample_csv = io.StringIO()
    sample_rows = report.get("sample_rows", [])
    if sample_rows:
        writer = csv.DictWriter(sample_csv, fieldnames=list(sample_rows[0].keys()))
        writer.writeheader()
        writer.writerows(sample_rows)

    chart_png = _draw_kpi_plot_png(report.get("kpis", []))

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("summary_kpis.csv", summary_csv.getvalue())
        zf.writestr("segment_metrics.csv", segments_csv.getvalue())
        zf.writestr("prediction_samples.csv", sample_csv.getvalue())
        zf.writestr("kpi_plot.png", chart_png)
        zf.writestr("report.json", json.dumps(report, indent=2))
    zip_buf.seek(0)
    return zip_buf.read()

