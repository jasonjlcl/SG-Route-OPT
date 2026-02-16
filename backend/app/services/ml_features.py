from __future__ import annotations

import math
from datetime import datetime
from typing import Any


FEATURE_COLUMNS = [
    "base_duration_s",
    "distance_m",
    "hour",
    "day_of_week",
    "is_peak_hour",
    "is_weekend",
    "distance_per_base_s",
    "lat_diff",
    "lon_diff",
    "bearing_deg",
]


def _to_float(value: Any) -> float:
    return float(value)


def _bearing_deg(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float) -> float:
    lat1 = math.radians(origin_lat)
    lat2 = math.radians(dest_lat)
    dlon = math.radians(dest_lon - origin_lon)

    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0


def is_peak_hour(hour: int) -> int:
    return 1 if hour in {7, 8, 9, 17, 18, 19, 20} else 0


def fallback_duration(base_duration_s: float, hour: int) -> float:
    if 7 <= hour <= 9:
        peak_factor = 0.25
    elif 17 <= hour <= 20:
        peak_factor = 0.28
    elif 10 <= hour <= 16:
        peak_factor = 0.12
    else:
        peak_factor = 0.05
    return max(1.0, float(base_duration_s) * (1 + peak_factor))


def build_feature_dict(
    *,
    base_duration_s: float,
    distance_m: float,
    depart_dt: datetime,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
) -> dict[str, float]:
    hour = int(depart_dt.hour)
    day_of_week = int(depart_dt.weekday())
    base = max(1.0, _to_float(base_duration_s))
    distance = max(0.0, _to_float(distance_m))
    o_lat = _to_float(origin_lat)
    o_lon = _to_float(origin_lon)
    d_lat = _to_float(dest_lat)
    d_lon = _to_float(dest_lon)

    return {
        "base_duration_s": base,
        "distance_m": distance,
        "hour": float(hour),
        "day_of_week": float(day_of_week),
        "is_peak_hour": float(is_peak_hour(hour)),
        "is_weekend": float(1 if day_of_week >= 5 else 0),
        "distance_per_base_s": float(distance / base),
        "lat_diff": float(d_lat - o_lat),
        "lon_diff": float(d_lon - o_lon),
        "bearing_deg": float(_bearing_deg(o_lat, o_lon, d_lat, d_lon)),
    }


def feature_vector(feature_dict: dict[str, float]) -> list[float]:
    return [float(feature_dict[name]) for name in FEATURE_COLUMNS]

