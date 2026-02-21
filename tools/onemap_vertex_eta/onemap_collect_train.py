#!/usr/bin/env python3
"""Build SG address stand-in pool, collect OneMap ETA labels, and train Vertex Tabular model.

Python: 3.11+
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import math
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests


LOGGER = logging.getLogger("onemap_collect_train")

DATA_GOV_POLL_URL = "https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/poll-download"
DEFAULT_WORKDIR = Path("backend/data/onemap_vertex_eta")
DEFAULT_BQ_DATASET = os.getenv("BQ_DATASET", "eta_sg")
DEFAULT_BQ_TABLE = os.getenv("BQ_TABLE", "onemap_eta_training")
DEFAULT_GCP_REGION = os.getenv("GCP_REGION", "asia-southeast1")
SG_TZ = ZoneInfo("Asia/Singapore")

SG_BOUNDS = {
    "lat_min": 1.15,
    "lat_max": 1.48,
    "lon_min": 103.58,
    "lon_max": 104.12,
}

DISTANCE_BUCKETS_KM: dict[str, tuple[float, float]] = {
    "1_3km": (1.0, 3.0),
    "3_8km": (3.0, 8.0),
    "8_20km": (8.0, 20.0),
}

DATASETS: dict[str, str] = {
    "d_5d668e3f544335f8028f546827b773b4": "Child Care Services",
    "d_4a086da0a5553be1d89383cd90d07ecd": "Hawker Centres",
    "d_9de02d3fb33d96da1855f4fbef549a0f": "Community Club / PAssion WaVe Outlet",
    "d_9b87bab59d036a60fad2a91530e10773": "SportSG Sport Facilities",
}

OPEN_DATA_ATTRIBUTION = (
    "Contains information from data.gov.sg, licensed under the Singapore Open Data Licence."
)


@dataclass(frozen=True)
class AddressRecord:
    point_id: str
    lat: float
    lon: float
    dataset_source: str
    dataset_id: str
    postal_code: str | None
    street_address: str | None


@dataclass(frozen=True)
class ODRecord:
    od_id: str
    origin_point_id: str
    origin_lat: float
    origin_lon: float
    origin_dataset_source: str
    dest_point_id: str
    dest_lat: float
    dest_lon: float
    dest_dataset_source: str
    distance_km: float
    distance_bucket: str


def _now_iso_sg() -> str:
    return datetime.now(tz=SG_TZ).isoformat()


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"na", "n/a", "none", "null", "<na>"}:
        return None
    return text


def _within_sg(lat: float, lon: float) -> bool:
    return (
        SG_BOUNDS["lat_min"] <= lat <= SG_BOUNDS["lat_max"]
        and SG_BOUNDS["lon_min"] <= lon <= SG_BOUNDS["lon_max"]
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    p = math.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlon / 2) ** 2
    )
    return 2.0 * radius_km * math.asin(math.sqrt(a))


def _bucket_for_distance(distance_km: float) -> str | None:
    for name, (lower, upper) in DISTANCE_BUCKETS_KM.items():
        if lower <= distance_km < upper:
            return name
    return None


def _retry_sleep_seconds(*, attempt: int, response: requests.Response | None = None) -> float:
    """Compute bounded backoff and honor provider hints for 429 throttling."""
    backoff = min(4.0, 0.25 * (2**attempt))
    if response is None or response.status_code != 429:
        return backoff

    retry_after = _safe_text(response.headers.get("Retry-After"))
    if retry_after:
        try:
            return max(10.0, float(retry_after))
        except ValueError:
            pass

    # data.gov.sg explicitly asks for a 10s wait when throttled.
    return max(10.0, backoff)


def _request_json_with_retries(
    session: requests.Session,
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout_s: int = 30,
    max_attempts: int = 5,
) -> dict[str, Any]:
    for attempt in range(max_attempts):
        try:
            response = session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=timeout_s,
            )
        except requests.RequestException as exc:
            if attempt == max_attempts - 1:
                raise RuntimeError(f"Request error for {url}: {exc}") from exc
            time.sleep(_retry_sleep_seconds(attempt=attempt))
            continue

        if response.status_code in {429, 500, 502, 503, 504}:
            if attempt == max_attempts - 1:
                raise RuntimeError(
                    f"Request failed for {url} with status {response.status_code}: {response.text[:300]}"
                )
            time.sleep(_retry_sleep_seconds(attempt=attempt, response=response))
            continue

        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"Non-JSON response from {url}") from exc

    raise RuntimeError(f"Failed request after retries: {url}")


def _download_geojson_with_retries(
    session: requests.Session,
    *,
    url: str,
    timeout_s: int = 60,
    max_attempts: int = 5,
) -> dict[str, Any]:
    for attempt in range(max_attempts):
        try:
            response = session.get(url, timeout=timeout_s)
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt == max_attempts - 1:
                    raise RuntimeError(
                        f"GeoJSON download failed {response.status_code}: {response.text[:300]}"
                    )
                time.sleep(_retry_sleep_seconds(attempt=attempt, response=response))
                continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt == max_attempts - 1:
                raise RuntimeError(f"Failed downloading GeoJSON: {url}: {exc}") from exc
            time.sleep(_retry_sleep_seconds(attempt=attempt))
    raise RuntimeError(f"Unable to download GeoJSON from {url}")


def _extract_property(properties: dict[str, Any], candidates: list[str]) -> str | None:
    lowered = {str(k).lower(): v for k, v in properties.items()}
    for key in candidates:
        if key.lower() in lowered:
            value = _safe_text(lowered[key.lower()])
            if value:
                return value
    return None


def _extract_address_metadata(properties: dict[str, Any]) -> tuple[str | None, str | None]:
    postal = _extract_property(
        properties,
        ["postal", "postal_code", "postalcode", "postcode", "post_code", "zip", "zip_code"],
    )
    street = _extract_property(
        properties,
        [
            "address",
            "street",
            "road_name",
            "road",
            "street_name",
            "blk_no",
            "block",
            "description",
            "name",
        ],
    )
    return postal, street


def _feature_to_address(
    feature: dict[str, Any],
    *,
    dataset_id: str,
    dataset_source: str,
    seen: set[tuple[str, float, float]],
) -> AddressRecord | None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        return None
    if str(geometry.get("type", "")).lower() != "point":
        return None

    coords = geometry.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None

    try:
        lon = float(coords[0])
        lat = float(coords[1])
    except (TypeError, ValueError):
        return None

    if not _within_sg(lat, lon):
        return None

    lat6 = round(lat, 6)
    lon6 = round(lon, 6)
    key = (dataset_id, lat6, lon6)
    if key in seen:
        return None
    seen.add(key)

    properties = feature.get("properties")
    props = properties if isinstance(properties, dict) else {}
    postal_code, street_address = _extract_address_metadata(props)
    point_id = f"pt_{hashlib.sha1(f'{dataset_id}:{lat6}:{lon6}'.encode('utf-8')).hexdigest()[:16]}"

    return AddressRecord(
        point_id=point_id,
        lat=lat6,
        lon=lon6,
        dataset_source=dataset_source,
        dataset_id=dataset_id,
        postal_code=postal_code,
        street_address=street_address,
    )


def _fetch_geojson_features(
    session: requests.Session,
    *,
    dataset_id: str,
    api_key: str | None,
) -> list[dict[str, Any]]:
    headers: dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key

    poll_url = DATA_GOV_POLL_URL.format(dataset_id=dataset_id)
    payload = _request_json_with_retries(
        session,
        method="GET",
        url=poll_url,
        headers=headers,
    )

    code = payload.get("code")
    if code not in {0, "0", None}:
        err = payload.get("errMsg") or payload.get("errorMsg") or str(payload)
        raise RuntimeError(f"poll-download failed for {dataset_id}: code={code}, message={err}")

    data_obj = payload.get("data")
    if not isinstance(data_obj, dict):
        raise RuntimeError(f"poll-download response missing data object for {dataset_id}")
    download_url = _safe_text(data_obj.get("url"))
    if not download_url:
        raise RuntimeError(f"poll-download response missing data.url for {dataset_id}")

    geojson = _download_geojson_with_retries(session, url=download_url)
    features = geojson.get("features")
    if not isinstance(features, list):
        raise RuntimeError(f"GeoJSON payload for {dataset_id} does not contain features[]")
    return features


def build_address_pool(
    *,
    addresses_csv: Path,
    metadata_csv: Path,
    summary_json: Path,
    api_key: str | None,
) -> dict[str, Any]:
    addresses_csv.parent.mkdir(parents=True, exist_ok=True)
    metadata_csv.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    seen: set[tuple[str, float, float]] = set()
    collected: list[AddressRecord] = []
    stats: dict[str, int] = {}

    for dataset_id, dataset_source in DATASETS.items():
        features = _fetch_geojson_features(session, dataset_id=dataset_id, api_key=api_key)
        accepted = 0
        for feature in features:
            if not isinstance(feature, dict):
                continue
            rec = _feature_to_address(
                feature,
                dataset_id=dataset_id,
                dataset_source=dataset_source,
                seen=seen,
            )
            if rec is None:
                continue
            collected.append(rec)
            accepted += 1
        stats[dataset_id] = accepted
        LOGGER.info("Accepted %s point(s) from %s (%s)", accepted, dataset_source, dataset_id)

    collected.sort(key=lambda item: (item.dataset_source, item.point_id))

    with addresses_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["point_id", "lat", "lon", "dataset_source"])
        for rec in collected:
            writer.writerow([rec.point_id, f"{rec.lat:.6f}", f"{rec.lon:.6f}", rec.dataset_source])

    with metadata_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["point_id", "dataset_id", "dataset_source", "postal_code", "street_address"])
        for rec in collected:
            writer.writerow(
                [
                    rec.point_id,
                    rec.dataset_id,
                    rec.dataset_source,
                    rec.postal_code or "",
                    rec.street_address or "",
                ]
            )

    summary = {
        "generated_at": _now_iso_sg(),
        "address_count": len(collected),
        "datasets": [
            {
                "dataset_id": dataset_id,
                "dataset_source": DATASETS[dataset_id],
                "accepted_points": stats.get(dataset_id, 0),
                "dataset_url": f"https://data.gov.sg/datasets/{dataset_id}/view",
            }
            for dataset_id in DATASETS
        ],
        "attribution": OPEN_DATA_ATTRIBUTION,
        "outputs": {
            "addresses_csv": str(addresses_csv),
            "metadata_csv": str(metadata_csv),
        },
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _read_addresses(addresses_csv: Path) -> list[AddressRecord]:
    if not addresses_csv.exists():
        raise FileNotFoundError(f"Address pool not found: {addresses_csv}")
    rows: list[AddressRecord] = []
    with addresses_csv.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            point_id = _safe_text(row.get("point_id"))
            dataset_source = _safe_text(row.get("dataset_source"))
            if not point_id or not dataset_source:
                continue
            try:
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append(
                AddressRecord(
                    point_id=point_id,
                    lat=lat,
                    lon=lon,
                    dataset_source=dataset_source,
                    dataset_id="",
                    postal_code=None,
                    street_address=None,
                )
            )
    if len(rows) < 2:
        raise RuntimeError("Address pool must have at least 2 valid rows")
    return rows


def _target_bucket_counts(target_rows: int) -> dict[str, int]:
    if target_rows <= 0:
        raise ValueError("target_rows must be > 0")
    c1 = int(target_rows * 0.4)
    c2 = int(target_rows * 0.4)
    c3 = target_rows - c1 - c2
    return {"1_3km": c1, "3_8km": c2, "8_20km": c3}


def sample_od_pairs(
    *,
    addresses: list[AddressRecord],
    sample_rows: int,
    seed: int,
    run_id: str,
) -> tuple[list[ODRecord], dict[str, int]]:
    rng = random.Random(seed)
    targets = _target_bucket_counts(sample_rows)
    counts = {bucket: 0 for bucket in targets}
    od_rows: list[ODRecord] = []
    used_pairs: set[tuple[str, str]] = set()

    n = len(addresses)
    max_attempts_unique = max(200_000, sample_rows * 300)
    attempts = 0

    while attempts < max_attempts_unique and any(counts[k] < targets[k] for k in targets):
        i = rng.randrange(n)
        j = rng.randrange(n - 1)
        if j >= i:
            j += 1
        origin = addresses[i]
        dest = addresses[j]
        pair_key = (origin.point_id, dest.point_id)
        if pair_key in used_pairs:
            attempts += 1
            continue
        distance_km = _haversine_km(origin.lat, origin.lon, dest.lat, dest.lon)
        bucket = _bucket_for_distance(distance_km)
        if not bucket or counts[bucket] >= targets[bucket]:
            attempts += 1
            continue

        used_pairs.add(pair_key)
        counts[bucket] += 1
        od_rows.append(
            ODRecord(
                od_id="",
                origin_point_id=origin.point_id,
                origin_lat=origin.lat,
                origin_lon=origin.lon,
                origin_dataset_source=origin.dataset_source,
                dest_point_id=dest.point_id,
                dest_lat=dest.lat,
                dest_lon=dest.lon,
                dest_dataset_source=dest.dataset_source,
                distance_km=round(distance_km, 6),
                distance_bucket=bucket,
            )
        )
        attempts += 1

    # Fallback with replacement if unique sampling cannot satisfy exact mix.
    max_attempts_replacement = max(300_000, sample_rows * 600)
    replacement_attempts = 0
    while replacement_attempts < max_attempts_replacement and any(counts[k] < targets[k] for k in targets):
        i = rng.randrange(n)
        j = rng.randrange(n - 1)
        if j >= i:
            j += 1
        origin = addresses[i]
        dest = addresses[j]
        distance_km = _haversine_km(origin.lat, origin.lon, dest.lat, dest.lon)
        bucket = _bucket_for_distance(distance_km)
        if not bucket or counts[bucket] >= targets[bucket]:
            replacement_attempts += 1
            continue

        counts[bucket] += 1
        od_rows.append(
            ODRecord(
                od_id="",
                origin_point_id=origin.point_id,
                origin_lat=origin.lat,
                origin_lon=origin.lon,
                origin_dataset_source=origin.dataset_source,
                dest_point_id=dest.point_id,
                dest_lat=dest.lat,
                dest_lon=dest.lon,
                dest_dataset_source=dest.dataset_source,
                distance_km=round(distance_km, 6),
                distance_bucket=bucket,
            )
        )
        replacement_attempts += 1

    if any(counts[k] < targets[k] for k in targets):
        raise RuntimeError(
            f"Unable to satisfy distance-mix targets. targets={targets}, achieved={counts}. "
            "Try building a larger address pool or lowering sample size."
        )

    rng.shuffle(od_rows)
    finalized: list[ODRecord] = []
    for idx, row in enumerate(od_rows, start=1):
        finalized.append(
            ODRecord(
                od_id=f"{run_id}_{idx:06d}",
                origin_point_id=row.origin_point_id,
                origin_lat=row.origin_lat,
                origin_lon=row.origin_lon,
                origin_dataset_source=row.origin_dataset_source,
                dest_point_id=row.dest_point_id,
                dest_lat=row.dest_lat,
                dest_lon=row.dest_lon,
                dest_dataset_source=row.dest_dataset_source,
                distance_km=row.distance_km,
                distance_bucket=row.distance_bucket,
            )
        )
    return finalized, counts


def write_od_pairs(od_csv: Path, od_rows: list[ODRecord]) -> None:
    od_csv.parent.mkdir(parents=True, exist_ok=True)
    with od_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "od_id",
                "origin_point_id",
                "origin_lat",
                "origin_lon",
                "origin_dataset_source",
                "dest_point_id",
                "dest_lat",
                "dest_lon",
                "dest_dataset_source",
                "distance_km",
                "distance_bucket",
            ]
        )
        for row in od_rows:
            writer.writerow(
                [
                    row.od_id,
                    row.origin_point_id,
                    f"{row.origin_lat:.6f}",
                    f"{row.origin_lon:.6f}",
                    row.origin_dataset_source,
                    row.dest_point_id,
                    f"{row.dest_lat:.6f}",
                    f"{row.dest_lon:.6f}",
                    row.dest_dataset_source,
                    f"{row.distance_km:.6f}",
                    row.distance_bucket,
                ]
            )


class OneMapRoutingClient:
    def __init__(
        self,
        *,
        email: str,
        password: str,
        auth_url: str,
        routing_url: str,
        timeout_s: int = 20,
        max_attempts: int = 5,
    ) -> None:
        if not email or not password:
            raise ValueError("ONEMAP_EMAIL and ONEMAP_PASSWORD are required for routing labels.")
        self.email = email
        self.password = password
        self.auth_url = auth_url
        self.routing_url = routing_url
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.session = requests.Session()
        self._token: str | None = None
        self._token_expiry_epoch: int = 0

    def _token_valid(self) -> bool:
        return bool(self._token) and int(time.time()) + 30 < self._token_expiry_epoch

    def _parse_token_expiry(self, payload: dict[str, Any]) -> int:
        now = int(time.time())
        raw = payload.get("expiry_timestamp") or payload.get("expiry")
        if isinstance(raw, (int, float)):
            expiry = int(raw)
            if expiry > now + 30:
                return expiry
        if isinstance(raw, str):
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return int(parsed.timestamp())
            except ValueError:
                pass
        return now + 3600

    def _refresh_token(self) -> None:
        payload = _request_json_with_retries(
            self.session,
            method="POST",
            url=self.auth_url,
            json_body={"email": self.email, "password": self.password},
            timeout_s=self.timeout_s,
            max_attempts=self.max_attempts,
        )
        token = _safe_text(payload.get("access_token") or payload.get("token"))
        if not token:
            raise RuntimeError("OneMap auth response missing access token")
        self._token = token
        self._token_expiry_epoch = self._parse_token_expiry(payload)

    def _auth_header(self) -> dict[str, str]:
        if not self._token_valid():
            self._refresh_token()
        return {"Authorization": f"Bearer {self._token}"}

    def route_duration(self, *, origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float) -> tuple[float, float]:
        refreshed = False
        for attempt in range(self.max_attempts):
            headers = self._auth_header()
            try:
                response = self.session.get(
                    self.routing_url,
                    params={
                        "start": f"{origin_lat},{origin_lon}",
                        "end": f"{dest_lat},{dest_lon}",
                        "routeType": "drive",
                    },
                    headers=headers,
                    timeout=self.timeout_s,
                )
            except requests.RequestException as exc:
                if attempt == self.max_attempts - 1:
                    raise RuntimeError(f"OneMap routing request failed: {exc}") from exc
                time.sleep(_retry_sleep_seconds(attempt=attempt))
                continue

            if response.status_code == 401 and not refreshed:
                self._token = None
                self._token_expiry_epoch = 0
                refreshed = True
                continue

            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt == self.max_attempts - 1:
                    raise RuntimeError(
                        f"OneMap routing failed with status {response.status_code}: {response.text[:300]}"
                    )
                time.sleep(_retry_sleep_seconds(attempt=attempt, response=response))
                continue

            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError("OneMap routing returned invalid JSON") from exc

            summary = payload.get("route_summary")
            if not isinstance(summary, dict):
                raise RuntimeError("OneMap routing payload missing route_summary")

            try:
                distance_m = float(summary.get("total_distance"))
                duration_s = float(summary.get("total_time"))
            except (TypeError, ValueError) as exc:
                raise RuntimeError("OneMap routing payload has invalid total_distance/total_time") from exc

            if distance_m <= 0 or duration_s <= 0:
                raise RuntimeError("OneMap routing payload returned non-positive distance/duration")
            return duration_s, distance_m

        raise RuntimeError("OneMap routing failed after retries")


class BigQuerySink:
    def __init__(self, *, project_id: str, region: str, dataset: str, table: str) -> None:
        from google.cloud import bigquery  # lazy import for non-GCP commands

        self.bigquery = bigquery
        self.client = bigquery.Client(project=project_id)
        self.project_id = project_id
        self.region = region
        self.dataset = dataset
        self.table = table
        self.table_id = f"{project_id}.{dataset}.{table}"

    def ensure_dataset_and_table(self) -> None:
        dataset_ref = self.bigquery.Dataset(f"{self.project_id}.{self.dataset}")
        dataset_ref.location = self.region
        self.client.create_dataset(dataset_ref, exists_ok=True)

        schema = [
            self.bigquery.SchemaField("od_id", "STRING", mode="REQUIRED"),
            self.bigquery.SchemaField("run_id", "STRING", mode="REQUIRED"),
            self.bigquery.SchemaField("origin_point_id", "STRING", mode="REQUIRED"),
            self.bigquery.SchemaField("origin_dataset_source", "STRING"),
            self.bigquery.SchemaField("origin_lat", "FLOAT64", mode="REQUIRED"),
            self.bigquery.SchemaField("origin_lon", "FLOAT64", mode="REQUIRED"),
            self.bigquery.SchemaField("dest_point_id", "STRING", mode="REQUIRED"),
            self.bigquery.SchemaField("dest_dataset_source", "STRING"),
            self.bigquery.SchemaField("dest_lat", "FLOAT64", mode="REQUIRED"),
            self.bigquery.SchemaField("dest_lon", "FLOAT64", mode="REQUIRED"),
            self.bigquery.SchemaField("distance_km", "FLOAT64", mode="REQUIRED"),
            self.bigquery.SchemaField("distance_bucket", "STRING", mode="REQUIRED"),
            self.bigquery.SchemaField("actual_duration_s", "FLOAT64", mode="REQUIRED"),
            self.bigquery.SchemaField("route_distance_m", "FLOAT64", mode="REQUIRED"),
            self.bigquery.SchemaField("timestamp_iso", "TIMESTAMP", mode="REQUIRED"),
            self.bigquery.SchemaField("label_source", "STRING", mode="REQUIRED"),
            self.bigquery.SchemaField("dataset_attribution", "STRING", mode="REQUIRED"),
        ]

        table_ref = self.bigquery.Table(self.table_id, schema=schema)
        table_ref.time_partitioning = self.bigquery.TimePartitioning(
            type_=self.bigquery.TimePartitioningType.DAY,
            field="timestamp_iso",
        )
        self.client.create_table(table_ref, exists_ok=True)

    def insert_rows(self, rows: list[dict[str, Any]], *, batch_size: int = 500) -> None:
        if not rows:
            return
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            row_ids = [f"{row['run_id']}:{row['od_id']}" for row in chunk]
            errors = self.client.insert_rows_json(self.table_id, chunk, row_ids=row_ids)
            if errors:
                raise RuntimeError(f"BigQuery insert_rows_json errors: {errors}")


def label_with_onemap_and_upload(
    *,
    od_rows: list[ODRecord],
    target_rows: int,
    sleep_ms: int,
    sink: BigQuerySink,
    labels_csv: Path,
    onemap_client: OneMapRoutingClient,
) -> dict[str, Any]:
    labels_csv.parent.mkdir(parents=True, exist_ok=True)
    buffer_rows: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    inserted = 0
    failed = 0
    run_id = od_rows[0].od_id.split("_")[0] if od_rows else "run"

    for od in od_rows:
        try:
            duration_s, route_distance_m = onemap_client.route_duration(
                origin_lat=od.origin_lat,
                origin_lon=od.origin_lon,
                dest_lat=od.dest_lat,
                dest_lon=od.dest_lon,
            )
            stamp = _now_iso_sg()
            row = {
                "od_id": od.od_id,
                "run_id": run_id,
                "origin_point_id": od.origin_point_id,
                "origin_dataset_source": od.origin_dataset_source,
                "origin_lat": od.origin_lat,
                "origin_lon": od.origin_lon,
                "dest_point_id": od.dest_point_id,
                "dest_dataset_source": od.dest_dataset_source,
                "dest_lat": od.dest_lat,
                "dest_lon": od.dest_lon,
                "distance_km": od.distance_km,
                "distance_bucket": od.distance_bucket,
                "actual_duration_s": float(duration_s),
                "route_distance_m": float(route_distance_m),
                "timestamp_iso": stamp,
                "label_source": "onemap_route",
                "dataset_attribution": OPEN_DATA_ATTRIBUTION,
            }
            buffer_rows.append(row)
            csv_rows.append(row)
            if len(buffer_rows) >= 500:
                sink.insert_rows(buffer_rows)
                inserted += len(buffer_rows)
                buffer_rows = []
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            LOGGER.warning("Label failed for %s: %s", od.od_id, exc)
            continue

    if buffer_rows:
        sink.insert_rows(buffer_rows)
        inserted += len(buffer_rows)

    with labels_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "od_id",
                "run_id",
                "origin_point_id",
                "origin_dataset_source",
                "origin_lat",
                "origin_lon",
                "dest_point_id",
                "dest_dataset_source",
                "dest_lat",
                "dest_lon",
                "distance_km",
                "distance_bucket",
                "actual_duration_s",
                "route_distance_m",
                "timestamp_iso",
                "label_source",
                "dataset_attribution",
            ]
        )
        for row in csv_rows:
            writer.writerow(
                [
                    row["od_id"],
                    row["run_id"],
                    row["origin_point_id"],
                    row["origin_dataset_source"],
                    f"{float(row['origin_lat']):.6f}",
                    f"{float(row['origin_lon']):.6f}",
                    row["dest_point_id"],
                    row["dest_dataset_source"],
                    f"{float(row['dest_lat']):.6f}",
                    f"{float(row['dest_lon']):.6f}",
                    f"{float(row['distance_km']):.6f}",
                    row["distance_bucket"],
                    f"{float(row['actual_duration_s']):.3f}",
                    f"{float(row['route_distance_m']):.3f}",
                    row["timestamp_iso"],
                    row["label_source"],
                    row["dataset_attribution"],
                ]
            )

    if inserted < target_rows:
        raise RuntimeError(
            f"Only {inserted} labeled rows inserted, below target_rows={target_rows}. "
            "Increase oversample factor or retry collection."
        )

    return {
        "inserted_rows": inserted,
        "failed_rows": failed,
        "labels_csv": str(labels_csv),
    }


def train_vertex_tabular_regression(
    *,
    project_id: str,
    region: str,
    bq_dataset: str,
    bq_table: str,
    target_column: str,
    vertex_dataset_display_name: str,
    training_job_display_name: str,
    model_display_name: str,
    budget_milli_node_hours: int,
) -> dict[str, Any]:
    from google.cloud import aiplatform  # lazy import

    aiplatform.init(project=project_id, location=region)
    bq_uri = f"bq://{project_id}.{bq_dataset}.{bq_table}"

    existing = aiplatform.TabularDataset.list(
        filter=f'display_name="{vertex_dataset_display_name}"',
        order_by="create_time desc",
    )
    if existing:
        tabular_dataset = existing[0]
        dataset_action = "reused"
    else:
        tabular_dataset = aiplatform.TabularDataset.create(
            display_name=vertex_dataset_display_name,
            bq_source=[bq_uri],
            sync=True,
        )
        dataset_action = "created"

    training_job = aiplatform.AutoMLTabularTrainingJob(
        display_name=training_job_display_name,
        optimization_prediction_type="regression",
        optimization_objective="minimize-rmse",
    )

    model = training_job.run(
        dataset=tabular_dataset,
        target_column=target_column,
        model_display_name=model_display_name,
        budget_milli_node_hours=budget_milli_node_hours,
        sync=True,
    )

    return {
        "trained_at": _now_iso_sg(),
        "project_id": project_id,
        "region": region,
        "bq_source": bq_uri,
        "target_column": target_column,
        "vertex_dataset_display_name": vertex_dataset_display_name,
        "vertex_dataset_action": dataset_action,
        "vertex_dataset_resource": getattr(tabular_dataset, "resource_name", None),
        "training_job_display_name": training_job_display_name,
        "training_job_resource": getattr(training_job, "resource_name", None),
        "model_display_name": model_display_name,
        "model_resource": getattr(model, "resource_name", None),
        "budget_milli_node_hours": budget_milli_node_hours,
    }


def _build_run_id() -> str:
    return datetime.now(tz=SG_TZ).strftime("run%Y%m%d%H%M%S")


def _required_env(name: str) -> str:
    value = _safe_text(os.getenv(name))
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_build_address_pool(args: argparse.Namespace) -> None:
    summary = build_address_pool(
        addresses_csv=Path(args.addresses_csv),
        metadata_csv=Path(args.metadata_csv),
        summary_json=Path(args.summary_json),
        api_key=_safe_text(args.datagov_api_key) or _safe_text(os.getenv("DATAGOV_API_KEY")),
    )
    print(json.dumps(summary, indent=2))


def run_collect(args: argparse.Namespace) -> None:
    addresses_csv = Path(args.addresses_csv)
    metadata_csv = Path(args.metadata_csv)
    build_summary_json = Path(args.build_summary_json)
    if not addresses_csv.exists() and args.build_if_missing:
        LOGGER.info("Address pool not found at %s. Building first...", addresses_csv)
        build_address_pool(
            addresses_csv=addresses_csv,
            metadata_csv=metadata_csv,
            summary_json=build_summary_json,
            api_key=_safe_text(args.datagov_api_key) or _safe_text(os.getenv("DATAGOV_API_KEY")),
        )

    run_id = _build_run_id()
    addresses = _read_addresses(addresses_csv)
    sample_rows = max(args.target_rows, math.ceil(args.target_rows * args.oversample_factor))
    od_rows, bucket_counts = sample_od_pairs(
        addresses=addresses,
        sample_rows=sample_rows,
        seed=args.seed,
        run_id=run_id,
    )
    write_od_pairs(Path(args.od_pairs_csv), od_rows)

    project_id = _safe_text(args.gcp_project_id) or _safe_text(os.getenv("GCP_PROJECT_ID"))
    if not project_id:
        raise RuntimeError("GCP project is required. Set --gcp_project_id or GCP_PROJECT_ID.")

    sink = BigQuerySink(
        project_id=project_id,
        region=_safe_text(args.gcp_region) or DEFAULT_GCP_REGION,
        dataset=_safe_text(args.bq_dataset) or DEFAULT_BQ_DATASET,
        table=_safe_text(args.bq_table) or DEFAULT_BQ_TABLE,
    )
    sink.ensure_dataset_and_table()

    onemap_client = OneMapRoutingClient(
        email=_required_env("ONEMAP_EMAIL"),
        password=_required_env("ONEMAP_PASSWORD"),
        auth_url=_safe_text(os.getenv("ONEMAP_AUTH_URL"))
        or "https://www.onemap.gov.sg/api/auth/post/getToken",
        routing_url=_safe_text(os.getenv("ONEMAP_ROUTING_URL"))
        or "https://www.onemap.gov.sg/api/public/routingsvc/route",
        timeout_s=args.timeout_s,
        max_attempts=args.max_attempts,
    )

    label_summary = label_with_onemap_and_upload(
        od_rows=od_rows,
        target_rows=args.target_rows,
        sleep_ms=args.sleep_ms,
        sink=sink,
        labels_csv=Path(args.labels_csv),
        onemap_client=onemap_client,
    )

    summary = {
        "run_id": run_id,
        "generated_at": _now_iso_sg(),
        "target_rows": args.target_rows,
        "sample_rows": sample_rows,
        "distance_mix_counts": bucket_counts,
        "od_pairs_csv": str(Path(args.od_pairs_csv)),
        "bigquery_table": f"{sink.project_id}.{sink.dataset}.{sink.table}",
        "attribution": OPEN_DATA_ATTRIBUTION,
        **label_summary,
    }
    _write_json(Path(args.collect_summary_json), summary)
    print(json.dumps(summary, indent=2))


def run_train(args: argparse.Namespace) -> None:
    project_id = _safe_text(args.gcp_project_id) or _safe_text(os.getenv("GCP_PROJECT_ID"))
    if not project_id:
        raise RuntimeError("GCP project is required. Set --gcp_project_id or GCP_PROJECT_ID.")

    stamp = datetime.now(tz=SG_TZ).strftime("%Y%m%d%H%M%S")
    model_display_name = _safe_text(args.model_display_name) or f"sg-onemap-eta-model-{stamp}"

    summary = train_vertex_tabular_regression(
        project_id=project_id,
        region=_safe_text(args.gcp_region) or DEFAULT_GCP_REGION,
        bq_dataset=_safe_text(args.bq_dataset) or DEFAULT_BQ_DATASET,
        bq_table=_safe_text(args.bq_table) or DEFAULT_BQ_TABLE,
        target_column=args.target_column,
        vertex_dataset_display_name=args.vertex_dataset_display_name,
        training_job_display_name=args.training_job_display_name,
        model_display_name=model_display_name,
        budget_milli_node_hours=args.budget_milli_node_hours,
    )
    _write_json(Path(args.train_summary_json), summary)
    print(json.dumps(summary, indent=2))


def run_collect_and_train(args: argparse.Namespace) -> None:
    collect_args = argparse.Namespace(**vars(args))
    train_args = argparse.Namespace(**vars(args))
    run_collect(collect_args)
    run_train(train_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pipeline for SG address stand-in pool creation, OD sampling, "
            "OneMap ETA label collection, and Vertex AutoML Tabular training."
        )
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    subparsers = parser.add_subparsers(dest="command", required=True)

    build_cmd = subparsers.add_parser("build-address-pool", help="Build addresses.csv from data.gov.sg GeoJSON datasets.")
    build_cmd.add_argument("--addresses-csv", default=str(DEFAULT_WORKDIR / "addresses.csv"))
    build_cmd.add_argument("--metadata-csv", default=str(DEFAULT_WORKDIR / "addresses_metadata.csv"))
    build_cmd.add_argument("--summary-json", default=str(DEFAULT_WORKDIR / "build_address_pool_summary.json"))
    build_cmd.add_argument("--datagov-api-key", default=None, help="Optional data.gov.sg API key (or DATAGOV_API_KEY env).")
    build_cmd.set_defaults(func=run_build_address_pool)

    collect_cmd = subparsers.add_parser("collect", help="Sample OD rows, label durations via OneMap, and load to BigQuery.")
    collect_cmd.add_argument("--addresses-csv", default=str(DEFAULT_WORKDIR / "addresses.csv"))
    collect_cmd.add_argument("--metadata-csv", default=str(DEFAULT_WORKDIR / "addresses_metadata.csv"))
    collect_cmd.add_argument("--build-summary-json", default=str(DEFAULT_WORKDIR / "build_address_pool_summary.json"))
    collect_cmd.add_argument("--od-pairs-csv", default=str(DEFAULT_WORKDIR / "od_pairs.csv"))
    collect_cmd.add_argument("--labels-csv", default=str(DEFAULT_WORKDIR / "onemap_labels.csv"))
    collect_cmd.add_argument("--collect-summary-json", default=str(DEFAULT_WORKDIR / "collect_summary.json"))
    collect_cmd.add_argument("--target_rows", type=int, default=20_000)
    collect_cmd.add_argument("--oversample_factor", type=float, default=1.3)
    collect_cmd.add_argument("--seed", type=int, default=42)
    collect_cmd.add_argument("--sleep_ms", type=int, default=200)
    collect_cmd.add_argument("--max-attempts", type=int, default=5)
    collect_cmd.add_argument("--timeout-s", type=int, default=20)
    collect_cmd.add_argument("--build-if-missing", action=argparse.BooleanOptionalAction, default=True)
    collect_cmd.add_argument("--datagov-api-key", default=None, help="Optional data.gov.sg API key (or DATAGOV_API_KEY env).")
    collect_cmd.add_argument("--gcp_project_id", default=None)
    collect_cmd.add_argument("--gcp_region", default=DEFAULT_GCP_REGION)
    collect_cmd.add_argument("--bq_dataset", default=DEFAULT_BQ_DATASET)
    collect_cmd.add_argument("--bq_table", default=DEFAULT_BQ_TABLE)
    collect_cmd.set_defaults(func=run_collect)

    train_cmd = subparsers.add_parser("train", help="Train Vertex AI AutoML Tabular regression model.")
    train_cmd.add_argument("--gcp_project_id", default=None)
    train_cmd.add_argument("--gcp_region", default=DEFAULT_GCP_REGION)
    train_cmd.add_argument("--bq_dataset", default=DEFAULT_BQ_DATASET)
    train_cmd.add_argument("--bq_table", default=DEFAULT_BQ_TABLE)
    train_cmd.add_argument("--target_column", default="actual_duration_s")
    train_cmd.add_argument("--vertex_dataset_display_name", default="sg-onemap-eta-tabular-dataset")
    train_cmd.add_argument("--training_job_display_name", default="sg-onemap-eta-automl-regression")
    train_cmd.add_argument("--model_display_name", default=None)
    train_cmd.add_argument("--budget_milli_node_hours", type=int, default=1_000)
    train_cmd.add_argument("--train-summary-json", default=str(DEFAULT_WORKDIR / "train_summary.json"))
    train_cmd.set_defaults(func=run_train)

    both_cmd = subparsers.add_parser("collect-and-train", help="Run collect, then train.")
    both_cmd.add_argument("--addresses-csv", default=str(DEFAULT_WORKDIR / "addresses.csv"))
    both_cmd.add_argument("--metadata-csv", default=str(DEFAULT_WORKDIR / "addresses_metadata.csv"))
    both_cmd.add_argument("--build-summary-json", default=str(DEFAULT_WORKDIR / "build_address_pool_summary.json"))
    both_cmd.add_argument("--od-pairs-csv", default=str(DEFAULT_WORKDIR / "od_pairs.csv"))
    both_cmd.add_argument("--labels-csv", default=str(DEFAULT_WORKDIR / "onemap_labels.csv"))
    both_cmd.add_argument("--collect-summary-json", default=str(DEFAULT_WORKDIR / "collect_summary.json"))
    both_cmd.add_argument("--target_rows", type=int, default=20_000)
    both_cmd.add_argument("--oversample_factor", type=float, default=1.3)
    both_cmd.add_argument("--seed", type=int, default=42)
    both_cmd.add_argument("--sleep_ms", type=int, default=200)
    both_cmd.add_argument("--max-attempts", type=int, default=5)
    both_cmd.add_argument("--timeout-s", type=int, default=20)
    both_cmd.add_argument("--build-if-missing", action=argparse.BooleanOptionalAction, default=True)
    both_cmd.add_argument("--datagov-api-key", default=None, help="Optional data.gov.sg API key (or DATAGOV_API_KEY env).")
    both_cmd.add_argument("--gcp_project_id", default=None)
    both_cmd.add_argument("--gcp_region", default=DEFAULT_GCP_REGION)
    both_cmd.add_argument("--bq_dataset", default=DEFAULT_BQ_DATASET)
    both_cmd.add_argument("--bq_table", default=DEFAULT_BQ_TABLE)
    both_cmd.add_argument("--target_column", default="actual_duration_s")
    both_cmd.add_argument("--vertex_dataset_display_name", default="sg-onemap-eta-tabular-dataset")
    both_cmd.add_argument("--training_job_display_name", default="sg-onemap-eta-automl-regression")
    both_cmd.add_argument("--model_display_name", default=None)
    both_cmd.add_argument("--budget_milli_node_hours", type=int, default=1_000)
    both_cmd.add_argument("--train-summary-json", default=str(DEFAULT_WORKDIR / "train_summary.json"))
    both_cmd.set_defaults(func=run_collect_and_train)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    args.func(args)


if __name__ == "__main__":
    main()
