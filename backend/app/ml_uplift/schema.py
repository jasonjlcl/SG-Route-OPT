from __future__ import annotations


UPLIFT_SAMPLE_COLUMNS = [
    "origin_lat",
    "origin_lng",
    "dest_lat",
    "dest_lng",
    "origin_zone",
    "dest_zone",
    "distance_m",
    "departure_time_iso",
    "time_bucket",
    "dow_bucket",
    "static_duration_s",
    "duration_s",
    "congestion_factor",
]

UPLIFT_FEATURE_COLUMNS = [
    "origin_zone",
    "dest_zone",
    "distance_m",
    "time_bucket",
    "dow_bucket",
    "static_duration_s",
]

UPLIFT_NUMERIC_COLUMNS = [
    "distance_m",
    "time_bucket",
    "dow_bucket",
    "static_duration_s",
]

UPLIFT_CATEGORICAL_COLUMNS = [
    "origin_zone",
    "dest_zone",
]

UPLIFT_TARGET_COLUMN = "congestion_factor"

