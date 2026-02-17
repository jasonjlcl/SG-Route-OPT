from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone


SG_TZ = timezone(timedelta(hours=8))


def parse_departure_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SG_TZ)
    return dt


def zone_bucket(lat: float, lng: float, *, grid_deg: float = 0.02) -> str:
    lat_bin = int(math.floor(float(lat) / float(grid_deg)))
    lng_bin = int(math.floor(float(lng) / float(grid_deg)))
    return f"z{lat_bin}_{lng_bin}"


def clamp_factor(value: float, *, lower: float = 0.7, upper: float = 2.5) -> float:
    return float(max(lower, min(upper, float(value))))


def build_uplift_row(
    *,
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    distance_m: float,
    departure_time_iso: str,
    static_duration_s: float,
    duration_s: float,
) -> dict[str, float | int | str]:
    dt = parse_departure_iso(departure_time_iso)
    safe_static = max(1.0, float(static_duration_s))
    safe_duration = max(1.0, float(duration_s))
    return {
        "origin_lat": float(origin_lat),
        "origin_lng": float(origin_lng),
        "dest_lat": float(dest_lat),
        "dest_lng": float(dest_lng),
        "origin_zone": zone_bucket(float(origin_lat), float(origin_lng)),
        "dest_zone": zone_bucket(float(dest_lat), float(dest_lng)),
        "distance_m": float(max(0.0, float(distance_m))),
        "departure_time_iso": dt.isoformat(),
        "time_bucket": int(dt.hour),
        "dow_bucket": int(dt.weekday()),
        "static_duration_s": float(safe_static),
        "duration_s": float(safe_duration),
        "congestion_factor": float(safe_duration / safe_static),
    }


def build_uplift_inference_row(
    *,
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    distance_m: float,
    departure_time_iso: str,
    static_duration_s: float,
) -> dict[str, float | int | str]:
    dt = parse_departure_iso(departure_time_iso)
    return {
        "origin_zone": zone_bucket(float(origin_lat), float(origin_lng)),
        "dest_zone": zone_bucket(float(dest_lat), float(dest_lng)),
        "distance_m": float(max(0.0, float(distance_m))),
        "time_bucket": int(dt.hour),
        "dow_bucket": int(dt.weekday()),
        "static_duration_s": float(max(1.0, float(static_duration_s))),
    }

