# OneMap -> Vertex ETA Pipeline (Python 3.11)

This pipeline builds a Singapore address stand-in pool from data.gov.sg GeoJSON datasets, samples origin-destination (OD) pairs, labels durations using OneMap routing, writes training rows to BigQuery, and trains a Vertex AI Tabular regression model.

## Deliverables

- `onemap_collect_train.py`
- `requirements.txt`
- `README.md`

## Data sources (data.gov.sg dataset IDs)

- `d_5d668e3f544335f8028f546827b773b4` - Child Care Services
- `d_4a086da0a5553be1d89383cd90d07ecd` - Hawker Centres
- `d_9de02d3fb33d96da1855f4fbef549a0f` - Community Club / PAssion WaVe Outlet
- `d_9b87bab59d036a60fad2a91530e10773` - SportSG Sport Facilities

## Compliance and attribution

Contains information from data.gov.sg licensed under the Singapore Open Data Licence.

- Attribution is included in generated summary metadata JSON files.
- Attribution is also written into the BigQuery training rows (`dataset_attribution` field).

## Install

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r tools/onemap_vertex_eta/requirements.txt
```

## Required environment variables

OneMap:

- `ONEMAP_EMAIL`
- `ONEMAP_PASSWORD`
- Optional overrides:
  - `ONEMAP_AUTH_URL` (default `https://www.onemap.gov.sg/api/auth/post/getToken`)
  - `ONEMAP_ROUTING_URL` (default `https://www.onemap.gov.sg/api/public/routingsvc/route`)

GCP / BigQuery / Vertex:

- `GCP_PROJECT_ID`
- Optional:
  - `GCP_REGION` (default `asia-southeast1`)
  - `BQ_DATASET` (default `eta_sg`)
  - `BQ_TABLE` (default `onemap_eta_training`)

Credentials:

- Ensure `GOOGLE_APPLICATION_CREDENTIALS` points to a service-account JSON with BigQuery and Vertex AI permissions.

## CLI commands

```bash
python tools/onemap_vertex_eta/onemap_collect_train.py build-address-pool
python tools/onemap_vertex_eta/onemap_collect_train.py collect --target_rows 20000 --sleep_ms 200
python tools/onemap_vertex_eta/onemap_collect_train.py train
python tools/onemap_vertex_eta/onemap_collect_train.py collect-and-train --target_rows 20000 --sleep_ms 200
```

## What each command does

### 1) `build-address-pool`

- Calls data.gov.sg `poll-download` endpoint for each dataset ID.
- Downloads GeoJSON, extracts `Point` geometry coordinates.
- Uses geometry `(lon, lat)` as lat/lon source (no geocoding).
- Drops null / invalid geometry and filters to SG bounds.
- Dedupe key: `(dataset_id, round(lat, 6), round(lon, 6))`.
- Outputs:
  - `backend/data/onemap_vertex_eta/addresses.csv`
    - columns: `point_id, lat, lon, dataset_source`
  - `backend/data/onemap_vertex_eta/addresses_metadata.csv`
  - `backend/data/onemap_vertex_eta/build_address_pool_summary.json`

### 2) `collect --target_rows 20000 --sleep_ms 200`

- Reads `addresses.csv`.
- Samples OD pairs with enforced distance mix:
  - 40% in `1-3km`
  - 40% in `3-8km`
  - 20% in `8-20km`
- Labels each OD via OneMap routing (`routeType=drive`) with retries/backoff.
- `timestamp_iso` is captured in `Asia/Singapore`.
- Creates/reuses BigQuery table:
  - `<GCP_PROJECT_ID>.<BQ_DATASET>.onemap_eta_training`
  - partitioned by day on `timestamp_iso`
- Writes labeled rows to BigQuery and local CSV:
  - `backend/data/onemap_vertex_eta/onemap_labels.csv`

### 3) `train`

- Creates/reuses Vertex `TabularDataset` from:
  - `bq://<project>.<bq_dataset>.<bq_table>`
- Trains AutoML Tabular Regression:
  - target column: `actual_duration_s`
- Saves summary:
  - `backend/data/onemap_vertex_eta/train_summary.json`

### 4) `collect-and-train`

- Runs `collect` then `train` in sequence.

## BigQuery schema

Rows include:

- `origin_lat`, `origin_lon`
- `dest_lat`, `dest_lon`
- `timestamp_iso`
- `actual_duration_s`

Plus metadata:

- `od_id`, `run_id`, `distance_km`, `distance_bucket`
- dataset source fields and attribution

## Notes

- This pipeline uses coordinates from source GeoJSON directly; it does not geocode.
- If OneMap routing returns too many failures, increase oversampling:
  - `--oversample_factor 1.5`
- For strict pacing, tune:
  - `--sleep_ms`
  - `--max-attempts`
  - `--timeout-s`
