from __future__ import annotations

import base64
import csv
import html
import io
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import qrcode
import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.models import Plan
from app.services.optimization import get_plan_details
from app.utils.errors import AppError, log_error
from app.utils.settings import get_settings

try:
    from weasyprint import HTML

    WEASYPRINT_AVAILABLE = True
except Exception:  # noqa: BLE001
    WEASYPRINT_AVAILABLE = False


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
MAP_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "maps"
MAP_CACHE_DIR.mkdir(parents=True, exist_ok=True)

ROUTE_COLORS = ["#109869", "#0f69d5", "#f97316", "#8b5cf6", "#ef4444", "#0ea5a4", "#db2777"]

jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def export_plan_csv(db: Session, plan_id: int) -> str:
    plan = get_plan_details(db, plan_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["vehicle_idx", "sequence", "stop_ref", "eta_iso", "address", "phone", "contact_name", "lat", "lon"])

    for route in plan["routes"]:
        for stop in route["stops"]:
            writer.writerow(
                [
                    route["vehicle_idx"],
                    stop["sequence_idx"],
                    stop["stop_ref"],
                    stop["eta_iso"],
                    stop["address"],
                    stop.get("phone"),
                    stop.get("contact_name"),
                    stop["lat"],
                    stop["lon"],
                ]
            )

    return output.getvalue()


def export_driver_csv(db: Session, plan_id: int) -> str:
    plan = get_plan_details(db, plan_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "vehicle",
            "seq",
            "stop_ref",
            "address",
            "planned_eta",
            "time_window",
            "service_window",
            "phone",
            "contact_name",
            "lat",
            "lon",
        ]
    )

    for route in plan["routes"]:
        for stop in route["stops"]:
            writer.writerow(
                [
                    route["vehicle_idx"],
                    stop["sequence_idx"],
                    stop["stop_ref"],
                    stop["address"],
                    _to_time(stop["eta_iso"]),
                    f"{_to_time(stop['arrival_window_start_iso'])} - {_to_time(stop['arrival_window_end_iso'])}",
                    f"{_to_time(stop['service_start_iso'])} - {_to_time(stop['service_end_iso'])}",
                    stop.get("phone"),
                    stop.get("contact_name"),
                    stop["lat"],
                    stop["lon"],
                ]
            )

    return output.getvalue()


def get_map_snapshot_svg(db: Session, plan_id: int, vehicle_idx: int | None = None) -> bytes:
    plan = get_plan_details(db, plan_id)
    routes = _select_routes(plan["routes"], vehicle_idx)
    if not routes:
        raise AppError(
            message="No routes available for map snapshot",
            error_code="NOT_FOUND",
            status_code=404,
            stage="EXPORT",
            details={"plan_id": plan_id, "vehicle_idx": vehicle_idx},
        )

    suffix = f"v{vehicle_idx}" if vehicle_idx is not None else "all"
    cache_file = MAP_CACHE_DIR / f"plan_{plan_id}_{suffix}.svg"

    if cache_file.exists():
        return cache_file.read_bytes()

    svg = _build_route_svg(routes)
    cache_file.write_text(svg, encoding="utf-8")
    return svg.encode("utf-8")


def export_plan_pdf(
    db: Session,
    plan_id: int,
    *,
    profile: str = "driver",
    vehicle_idx: int | None = None,
) -> bytes:
    try:
        plan = get_plan_details(db, plan_id)
        routes = _select_routes(plan["routes"], vehicle_idx)
        if not routes:
            raise AppError(
                message="No routes found for export",
                error_code="NOT_FOUND",
                status_code=404,
                stage="EXPORT",
                details={"plan_id": plan_id, "vehicle_idx": vehicle_idx},
            )

        summary = _build_summary(plan, routes)
        map_route_id = int(routes[0]["route_id"]) if vehicle_idx is not None and routes else None
        map_png = generate_map_png(db, plan_id, route_id=map_route_id, mode="single" if map_route_id is not None else "all")
        map_data_uri = f"data:image/png;base64,{base64.b64encode(map_png).decode('utf-8')}"

        route_sections = []
        for index, route in enumerate(routes):
            route_sections.append(
                {
                    "vehicle_idx": route["vehicle_idx"],
                    "color": ROUTE_COLORS[index % len(ROUTE_COLORS)],
                    "stops_count": max(0, len(route["stops"]) - 2),
                    "distance_km": round(float(route["total_distance_m"]) / 1000, 2),
                    "duration_min": max(1, round(float(route["total_duration_s"]) / 60)),
                    "start_time": _to_time(route["stops"][0]["eta_iso"]) if route["stops"] else "--:--",
                    "end_time": _to_time(route["stops"][-1]["eta_iso"]) if route["stops"] else "--:--",
                    "qr_data_uri": _route_qr_data_uri(route),
                    "rows": _build_route_rows(route),
                }
            )

        context = {
            "profile": profile,
            "title": "Driver Route Pack" if profile == "driver" else "Planner Route Pack",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "plan_id": plan_id,
            "dataset_id": plan["dataset_id"],
            "status": plan["status"],
            "depot": f"{plan['depot']['lat']:.5f}, {plan['depot']['lon']:.5f}",
            "summary": summary,
            "map_data_uri": map_data_uri,
            "routes": route_sections,
            "unserved_stops": plan.get("unserved_stops", []),
            "vehicle_scope": f"Vehicle {vehicle_idx}" if vehicle_idx is not None else "All Vehicles",
        }

        template = jinja_env.get_template("driver_pack.html")
        html_out = template.render(**context)

        if WEASYPRINT_AVAILABLE:
            try:
                return HTML(string=html_out, base_url=str(TEMPLATE_DIR)).write_pdf()
            except Exception:  # noqa: BLE001
                return _fallback_pdf(plan_id, routes)

        return _fallback_pdf(plan_id, routes)
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        log_error(db, "EXPORT", str(exc), details={"plan_id": plan_id, "vehicle_idx": vehicle_idx, "profile": profile})
        raise AppError(
            message="Failed to export PDF",
            error_code="EXPORT_ERROR",
            status_code=500,
            stage="EXPORT",
            details={"plan_id": plan_id, "vehicle_idx": vehicle_idx, "profile": profile},
        ) from exc


def _fallback_pdf(plan_id: int, routes: list[dict[str, Any]]) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    y = 800

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, f"Route Pack {plan_id}")
    y -= 24

    pdf.setFont("Helvetica", 10)
    for route in routes:
        pdf.drawString(40, y, f"Vehicle {route['vehicle_idx']} | Stops {max(0, len(route['stops']) - 2)}")
        y -= 14
        if y < 80:
            pdf.showPage()
            y = 800
            pdf.setFont("Helvetica", 10)

    pdf.save()
    buffer.seek(0)
    return buffer.read()


def _build_summary(plan: dict[str, Any], routes: list[dict[str, Any]]) -> dict[str, Any]:
    served = sum(1 for route in routes for stop in route["stops"] if stop["stop_ref"] != "DEPOT")
    total_distance = sum(float(route["total_distance_m"]) for route in routes)
    total_duration = sum(float(route["total_duration_s"]) for route in routes)
    makespan = float(plan.get("total_makespan_s") or 0)

    eta_values = [
        datetime.fromisoformat(stop["eta_iso"]).timestamp()
        for route in routes
        for stop in route["stops"]
        if stop.get("eta_iso")
    ]
    finish_time = datetime.fromtimestamp(max(eta_values)).strftime("%H:%M") if eta_values else "--:--"

    return {
        "vehicles": len(routes),
        "served_stops": served,
        "unserved_stops": len(plan.get("unserved_stops", [])),
        "distance_km": round(total_distance / 1000, 2),
        "duration_min": max(1, round((makespan if makespan > 0 else total_duration) / 60)),
        "sum_vehicle_duration_min": max(1, round(total_duration / 60)),
        "finish_time": finish_time,
    }


def _build_route_rows(route: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, stop in enumerate(route["stops"]):
        next_drive = "--"
        if i + 1 < len(route["stops"]):
            try:
                end_service = datetime.fromisoformat(stop["service_end_iso"])
                next_eta = datetime.fromisoformat(route["stops"][i + 1]["eta_iso"])
                mins = max(0, round((next_eta - end_service).total_seconds() / 60))
                next_drive = f"{mins} min"
            except Exception:  # noqa: BLE001
                next_drive = "--"

        rows.append(
            {
                "seq": stop["sequence_idx"],
                "stop_ref": stop["stop_ref"],
                "address": stop["address"],
                "eta": _to_time(stop["eta_iso"]),
                "time_window": f"{_to_time(stop['arrival_window_start_iso'])} - {_to_time(stop['arrival_window_end_iso'])}",
                "service_window": f"{_to_time(stop['service_start_iso'])} - {_to_time(stop['service_end_iso'])}",
                "service_time": _service_minutes(stop["service_start_iso"], stop["service_end_iso"]),
                "drive_to_next": next_drive,
                "notes": "Depot" if stop["stop_ref"] == "DEPOT" else "",
                "phone": stop.get("phone"),
                "contact_name": stop.get("contact_name"),
            }
        )
    return rows


def _route_qr_data_uri(route: dict[str, Any]) -> str:
    stops = [stop for stop in route["stops"] if stop["stop_ref"] != "DEPOT"]
    if not stops:
        return ""

    origin = f"{stops[0]['lat']},{stops[0]['lon']}"
    destination = f"{stops[-1]['lat']},{stops[-1]['lon']}"
    waypoints = "|".join(f"{stop['lat']},{stop['lon']}" for stop in stops[1:-1])
    waypoints_part = f"&waypoints={quote(waypoints)}" if waypoints else ""
    link = f"https://www.google.com/maps/dir/?api=1&origin={quote(origin)}&destination={quote(destination)}{waypoints_part}"

    qr = qrcode.QRCode(version=1, box_size=4, border=1)
    qr.add_data(link)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"


def _select_routes(routes: list[dict[str, Any]], vehicle_idx: int | None) -> list[dict[str, Any]]:
    if vehicle_idx is None:
        return routes
    return [route for route in routes if int(route["vehicle_idx"]) == int(vehicle_idx)]


def _service_minutes(service_start_iso: str, service_end_iso: str) -> str:
    try:
        start = datetime.fromisoformat(service_start_iso)
        end = datetime.fromisoformat(service_end_iso)
        mins = max(0, round((end - start).total_seconds() / 60))
        return f"{mins} min"
    except Exception:  # noqa: BLE001
        return "--"


def _to_time(iso_value: str) -> str:
    try:
        return datetime.fromisoformat(iso_value).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return "--:--"


def _build_route_svg(routes: list[dict[str, Any]], width: int = 1200, height: int = 640) -> str:
    points: list[tuple[float, float]] = []
    for route in routes:
        for stop in route["stops"]:
            points.append((float(stop["lon"]), float(stop["lat"])))

    if not points:
        return "<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='640'></svg>"

    min_lon = min(point[0] for point in points)
    max_lon = max(point[0] for point in points)
    min_lat = min(point[1] for point in points)
    max_lat = max(point[1] for point in points)

    lon_span = max(max_lon - min_lon, 0.0001)
    lat_span = max(max_lat - min_lat, 0.0001)
    pad = 44

    def transform(lon: float, lat: float) -> tuple[float, float]:
        x = pad + ((lon - min_lon) / lon_span) * (width - 2 * pad)
        y = height - pad - ((lat - min_lat) / lat_span) * (height - 2 * pad)
        return x, y

    elements: list[str] = [
        f"<rect x='0' y='0' width='{width}' height='{height}' fill='#f8fafc'/>",
        f"<rect x='18' y='18' width='{width - 36}' height='{height - 36}' rx='16' fill='white' stroke='#dbe2ea'/>",
    ]

    for idx, route in enumerate(routes):
        color = ROUTE_COLORS[idx % len(ROUTE_COLORS)]
        xy = [transform(float(stop["lon"]), float(stop["lat"])) for stop in route["stops"]]
        if len(xy) >= 2:
            path = " ".join(f"{x:.2f},{y:.2f}" for x, y in xy)
            elements.append(f"<polyline fill='none' stroke='{color}' stroke-width='4' stroke-linecap='round' points='{path}' />")

        for stop in route["stops"]:
            x, y = transform(float(stop["lon"]), float(stop["lat"]))
            label = html.escape(str(stop["sequence_idx"]))
            elements.append(f"<circle cx='{x:.2f}' cy='{y:.2f}' r='10' fill='{color}' stroke='white' stroke-width='2' />")
            elements.append(
                f"<text x='{x:.2f}' y='{y + 4:.2f}' text-anchor='middle' font-size='9' font-family='Arial' fill='white'>{label}</text>"
            )

    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'>{''.join(elements)}</svg>"
    return svg


def generate_map_png(
    db: Session,
    plan_id: int,
    *,
    route_id: int | None = None,
    mode: str = "all",
    progress_cb: Any | None = None,
) -> bytes:
    plan = get_plan_details(db, plan_id)
    selected_routes = plan["routes"]
    if mode == "single" and route_id is not None:
        selected_routes = [route for route in selected_routes if int(route["route_id"]) == int(route_id)]
    if not selected_routes:
        raise AppError(
            message="No routes available for map PNG",
            error_code="NOT_FOUND",
            status_code=404,
            stage="EXPORT",
            details={"plan_id": plan_id, "route_id": route_id, "mode": mode},
        )

    plan_row = db.get(Plan, plan_id)
    updated_stamp = str(int((plan_row.updated_at.timestamp() if plan_row and plan_row.updated_at else time.time())))
    suffix = f"{mode}_{route_id if route_id is not None else 'all'}_{updated_stamp}"
    cache_file = MAP_CACHE_DIR / f"plan_{plan_id}_{suffix}.png"
    if cache_file.exists():
        return cache_file.read_bytes()

    if progress_cb:
        progress_cb(40, "Rendering tile-accurate map snapshot")

    png = _render_map_png_with_playwright(plan_id=plan_id, route_id=route_id, mode=mode)
    if png is None:
        if progress_cb:
            progress_cb(70, "Playwright unavailable, using fallback renderer")
        # Do not cache fallback output to allow automatic recovery once frontend/playwright is available.
        return _build_route_png_fallback(selected_routes)

    cache_file.write_bytes(png)
    return png


def _render_map_png_with_playwright(*, plan_id: int, route_id: int | None, mode: str) -> bytes | None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        return None

    settings = get_settings()
    try:
        httpx.get(settings.frontend_base_url, timeout=1.5)
    except Exception:
        return None

    params = [f"plan_id={plan_id}", f"mode={mode}"]
    if route_id is not None:
        params.append(f"route_id={route_id}")
    url = f"{settings.frontend_base_url.rstrip('/')}/print/map?{'&'.join(params)}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_selector("#print-map-ready[data-ready='1']", timeout=25000)
            page.wait_for_function(
                "() => document.querySelectorAll('.leaflet-tile-loaded').length > 0 || document.querySelectorAll('.leaflet-tile-container img').length === 0",
                timeout=10000,
            )
            img = page.screenshot(type="png", full_page=False)
            browser.close()
            return img
    except Exception:
        return None


def _build_route_png_fallback(routes: list[dict[str, Any]], width: int = 1400, height: int = 900) -> bytes:
    points: list[tuple[float, float]] = []
    for route in routes:
        for stop in route["stops"]:
            points.append((float(stop["lon"]), float(stop["lat"])))

    if not points:
        image = Image.new("RGB", (width, height), (248, 250, 252))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    min_lon = min(point[0] for point in points)
    max_lon = max(point[0] for point in points)
    min_lat = min(point[1] for point in points)
    max_lat = max(point[1] for point in points)
    lon_span = max(max_lon - min_lon, 0.0001)
    lat_span = max(max_lat - min_lat, 0.0001)
    pad = 56

    def transform(lon: float, lat: float) -> tuple[int, int]:
        x = int(pad + ((lon - min_lon) / lon_span) * (width - 2 * pad))
        y = int(height - pad - ((lat - min_lat) / lat_span) * (height - 2 * pad))
        return x, y

    image = Image.new("RGB", (width, height), (248, 250, 252))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((18, 18, width - 18, height - 18), radius=18, outline=(219, 226, 234), fill=(255, 255, 255), width=2)

    for idx, route in enumerate(routes):
        color = ROUTE_COLORS[idx % len(ROUTE_COLORS)]
        rgb = tuple(int(color[k : k + 2], 16) for k in (1, 3, 5))
        xy = [transform(float(stop["lon"]), float(stop["lat"])) for stop in route["stops"]]
        if len(xy) >= 2:
            draw.line(xy, fill=rgb, width=5)
        for stop in route["stops"]:
            x, y = transform(float(stop["lon"]), float(stop["lat"]))
            draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=rgb, outline=(255, 255, 255), width=2)

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
