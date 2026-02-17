from __future__ import annotations

import argparse
import json
import math
import random
from datetime import datetime

from sqlalchemy import select

from app.models import Stop
from app.providers.google_routes import GoogleRoutesError, get_google_routes_provider
from app.ml_uplift.features import build_uplift_row
from app.ml_uplift.storage import append_samples
from app.utils.db import SessionLocal
from app.utils.settings import get_settings


def _load_points(dataset_id: int, *, max_points: int) -> list[dict[str, float]]:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Stop).where(Stop.dataset_id == dataset_id, Stop.geocode_status.in_(["SUCCESS", "MANUAL"]))
        ).scalars().all()
    finally:
        db.close()

    points = []
    for row in rows:
        if row.lat is None or row.lon is None:
            continue
        points.append({"lat": float(row.lat), "lng": float(row.lon)})

    random.Random(42).shuffle(points)
    return points[:max_points]


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect cost-aware Google traffic samples for ML uplift model")
    parser.add_argument("--dataset-id", type=int, required=True, help="Dataset ID with geocoded stops")
    parser.add_argument("--sample-elements", type=int, default=25, help="Approximate number of OD elements to collect")
    parser.add_argument("--departure-time-iso", type=str, default=None, help="Departure time in ISO format")
    parser.add_argument("--routing-preference", type=str, default="TRAFFIC_AWARE", help="Google routing preference")
    args = parser.parse_args()

    settings = get_settings()
    departure_iso = args.departure_time_iso or datetime.utcnow().isoformat()
    requested_elements = max(1, int(args.sample_elements))
    max_elements = int(settings.resolved_google_matrix_max_elements)
    side = max(2, int(math.sqrt(min(requested_elements, max_elements))))

    points = _load_points(args.dataset_id, max_points=max(4, side * 2))
    if len(points) < 2:
        print(json.dumps({"inserted_rows": 0, "reason": "not_enough_points"}))
        return

    origins = points[:side]
    destinations = points[:side]
    provider = get_google_routes_provider()
    if not provider.enabled:
        print(json.dumps({"inserted_rows": 0, "reason": "google_traffic_disabled"}))
        return

    try:
        matrix = provider.compute_route_matrix(
            origins=origins,
            destinations=destinations,
            departure_time_iso=departure_iso,
            routing_preference=args.routing_preference,
        )
    except GoogleRoutesError as exc:
        print(
            json.dumps(
                {
                    "inserted_rows": 0,
                    "reason": "google_error",
                    "code": exc.code,
                    "status_code": exc.status_code,
                    "details": exc.details,
                }
            )
        )
        return

    rows = []
    for i, origin in enumerate(origins):
        for j, destination in enumerate(destinations):
            if i == j:
                continue
            element = matrix[i][j] if i < len(matrix) and j < len(matrix[i]) else None
            if element is None:
                continue
            rows.append(
                build_uplift_row(
                    origin_lat=float(origin["lat"]),
                    origin_lng=float(origin["lng"]),
                    dest_lat=float(destination["lat"]),
                    dest_lng=float(destination["lng"]),
                    distance_m=float(element.distance_m),
                    departure_time_iso=departure_iso,
                    static_duration_s=float(element.static_duration_s),
                    duration_s=float(element.duration_s),
                )
            )
            if len(rows) >= requested_elements:
                break
        if len(rows) >= requested_elements:
            break

    inserted = append_samples(rows)
    print(
        json.dumps(
            {
                "dataset_id": int(args.dataset_id),
                "inserted_rows": int(inserted),
                "requested_elements": requested_elements,
                "max_elements_guardrail": max_elements,
                "routing_preference": args.routing_preference,
                "departure_time_iso": departure_iso,
            }
        )
    )


if __name__ == "__main__":
    main()

