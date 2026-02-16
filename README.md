# SG Route Optimization MVP

Local full-stack MVP for upload -> validate -> geocode -> optimize VRPTW -> visualize routes -> export CSV/PDF.

Architecture diagrams and gap-closure roadmap: `ARCHITECTURE.md`

## Modern UI/UX Layer

The frontend now uses a product-style shell with:

- Workflow step navigation: `Upload -> Validate -> Geocode -> Optimize -> Results`
- Top status bar with dataset context and export shortcuts
- Planner and Driver views in Results
- Improved actionable empty/loading/error states
- TailwindCSS + shadcn-style UI component layer + Lucide icons

Design system files:

- `frontend/src/design/tokens.ts`
- `frontend/src/components/ui/*`
- `frontend/src/components/layout/*`
- `frontend/src/components/status/*`
- `frontend/src/components/results/*`

## Stack

- Backend: Python 3.11, FastAPI, Pydantic, SQLAlchemy, Uvicorn
- Optimizer: OR-Tools (VRPTW + optional capacity)
- ML: scikit-learn baseline, fallback heuristic when model missing
- DB: SQLite (swap-ready for Postgres via `DATABASE_URL`)
- Cache/Queue: Redis + RQ job queue (inline fallback for local/test)
- Static map rendering: Playwright screenshot (PNG) with local fallback renderer
- Frontend: React + Vite + TypeScript + React-Leaflet
- External APIs: OneMap Search + OneMap Routing (mock mode if creds missing)

## Repo Structure

```text
/backend
  /app
    main.py
    /api
    /services
    /models
    /schemas
    /utils
    /tests
/frontend
/sample.env
docker-compose.yml
README.md
```

## Environment

Copy and edit:

```bash
cp .sample.env .env
```

Required env vars:

- `ONEMAP_EMAIL`
- `ONEMAP_PASSWORD`
- `REDIS_URL` (default `redis://redis:6379/0`)
- `APP_ENV`
- `MAX_UPLOAD_MB`

Optional:

- `DATABASE_URL` (default `sqlite:///./app.db`)
- `ALLOWED_ORIGINS` (default `http://localhost:5173`)
- `APP_BASE_URL` (default `http://localhost:8000`)
- `FRONTEND_BASE_URL` (default `http://localhost:5173`)
- `JOBS_FORCE_INLINE` (set `true` to run jobs in API process, useful without worker)
- `ML_DRIFT_THRESHOLD`
- `ML_RETRAIN_MIN_ROWS`

If OneMap credentials are empty, backend automatically uses deterministic mock geocoding/routing for local development.

## Local Run

### Backend

```bash
cd backend
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Worker (for async queue)

```bash
cd backend
rq worker default --url redis://localhost:6379/0
```

### Frontend

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Open: `http://localhost:5173`

## Workflow Usage (Planner)

1. Upload (`/upload`)
- Drag/drop CSV/XLSX
- Review validation summary
- Use `Proceed with valid stops` when partial errors exist
- Download `error log CSV` for offline fixes

2. Validate (`/validate`)
- Check dataset-level readiness and geocode counts before routing

3. Geocode (`/geocoding`)
- Run geocoding in batch (background job)
- Use `Retry failed stops`
- Resolve failures with corrected address or manual lat/lon
- Watch live job progress (SSE/poll) and resume after navigation

4. Optimize (`/optimization`)
- Configure depot, fleet, workday, solver options
- Run optimization (background job)
- If infeasible, apply suggestion chips and rerun
- Watch solver/matrix progress and resume after navigation

5. Results (`/results`)
- Planner View: map + route cards + stop sequence
- Planner Edit Mode: drag-drop stop resequencing + ETA recompute + violations
- Driver View: mobile-friendly route sheet (large text/tap targets)
- Exports tab: PDF/CSV outputs

## Driver Pack Exports

Backend exports now include:

- `GET /api/v1/plans/{plan_id}/export?format=pdf&profile=driver`
  - Combined Driver Route Pack PDF
- `GET /api/v1/plans/{plan_id}/export?format=pdf&profile=driver&vehicle_idx={i}`
  - Per-vehicle Driver PDF
- `GET /api/v1/plans/{plan_id}/export?format=csv`
  - Planner CSV
- `GET /api/v1/plans/{plan_id}/export/driver-csv`
  - Driver CSV
- `GET /api/v1/plans/{plan_id}/map-snapshot?vehicle_idx={i}`
  - Cached route map snapshot (SVG)
- `GET /api/v1/plans/{plan_id}/map.png?mode=all|single&route_id=...`
  - Cached route map image (PNG)
- `POST /api/v1/plans/{plan_id}/export?format=pdf...`
  - Async PDF generation job
- `POST /api/v1/plans/{plan_id}/map.png?mode=...`
  - Async map PNG generation job

PDF notes:

- HTML template: `backend/app/templates/driver_pack.html`
- Renderer: WeasyPrint when native libs are present
- Safe fallback: ReportLab PDF if WeasyPrint runtime libs are unavailable
- Map embedding prefers Playwright-rendered PNG (`/print/map`) when available

## Docker

```bash
docker compose up --build
```

Services:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- Redis: `localhost:6379`
- Worker: RQ queue worker for async jobs

## Input File Format

CSV or XLSX. Columns are case-insensitive.

Required:

- `stop_ref`
- `address` or `postal_code` (at least one)

Optional:

- `demand` (default 0)
- `service_time_min` (default 0)
- `tw_start` (`HH:MM`)
- `tw_end` (`HH:MM`)
- `phone`
- `contact_name`

### Sample CSV

```csv
stop_ref,address,postal_code,demand,service_time_min,tw_start,tw_end,phone,contact_name
S1,10 Bayfront Avenue,,1,5,09:00,12:00,+65 81234567,Jason Tan
S2,1 Raffles Place,,2,8,10:00,15:30,,
S3,,768024,1,6,09:30,16:00,91234567,Ops Desk
```

## API Endpoints

- `POST /api/v1/datasets/upload`
- `GET /api/v1/datasets/{dataset_id}`
- `GET /api/v1/datasets/{dataset_id}/stops?status=...`
- `POST /api/v1/datasets/{dataset_id}/geocode?failed_only=true|false`
- `POST /api/v1/stops/{stop_id}/geocode/manual`
- `POST /api/v1/datasets/{dataset_id}/optimize`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/events`
- `GET /api/v1/jobs/{job_id}/file`
- `GET /api/v1/plans/{plan_id}`
- `POST /api/v1/plans/{plan_id}/routes/{route_id}/resequence`
- `GET /api/v1/plans/{plan_id}/export?format=csv|pdf`
- `POST /api/v1/plans/{plan_id}/export?format=pdf`
- `GET /api/v1/plans/{plan_id}/export/driver-csv`
- `GET /api/v1/plans/{plan_id}/map-snapshot`
- `GET /api/v1/plans/{plan_id}/map.png`
- `POST /api/v1/plans/{plan_id}/map.png`
- `GET /api/v1/ml/models`
- `POST /api/v1/ml/models/train`
- `POST /api/v1/ml/rollout`
- `POST /api/v1/ml/actuals/upload`
- `GET /api/v1/ml/metrics/latest`
- `GET /api/v1/health`

## Curl Examples

### Upload

```bash
curl -X POST "http://localhost:8000/api/v1/datasets/upload" \
  -F "file=@./sample_stops.csv" \
  -F "exclude_invalid=true"
```

### Run Geocode

```bash
curl -X POST "http://localhost:8000/api/v1/datasets/1/geocode"
# => { "job_id": "...", ... }
curl "http://localhost:8000/api/v1/jobs/<job_id>"
```

### Optimize

```bash
curl -X POST "http://localhost:8000/api/v1/datasets/1/optimize" \
  -H "Content-Type: application/json" \
  -d '{
    "depot_lat": 1.3521,
    "depot_lon": 103.8198,
    "fleet": {"num_vehicles": 2, "capacity": 25},
    "workday_start": "08:00",
    "workday_end": "18:00",
    "solver": {"solver_time_limit_s": 15, "allow_drop_visits": true}
  }'
# => { "job_id": "...", ... }
curl "http://localhost:8000/api/v1/jobs/<job_id>"
```

### Get Plan + Exports

```bash
curl "http://localhost:8000/api/v1/plans/1"
curl -OJ "http://localhost:8000/api/v1/plans/1/export?format=csv"
curl -OJ "http://localhost:8000/api/v1/plans/1/export?format=pdf"
```

### Resequence Route

```bash
curl -X POST "http://localhost:8000/api/v1/plans/1/routes/10/resequence" \
  -H "Content-Type: application/json" \
  -d '{"ordered_stop_ids":[23,19,21],"apply":false}'
```

## ML Lifecycle (MVP)

Frontend admin page: `/ml`

Capabilities:

- Model registry listing and metrics
- Train model as background job (`POST /api/v1/ml/models/train`)
- Set active/canary rollout (`POST /api/v1/ml/rollout`)
- Upload actuals CSV (`POST /api/v1/ml/actuals/upload`)
- Latest MAE/MAPE + drift snapshot (`GET /api/v1/ml/metrics/latest`)
- Daily monitoring + weekly retrain-if-needed scheduler (backend startup)

### ML Training Script

Train a baseline model from historical OD data:

```bash
cd backend
python -m app.ml.train --input ./historical_routes.csv
```

Required columns:

- `origin_lat, origin_lon, dest_lat, dest_lon`
- `base_duration_s, timestamp, actual_duration_s`
- optional `distance_m`

Artifacts are saved in `backend/app/ml/artifacts/`.

### View Job Progress

- Poll: `GET /api/v1/jobs/{job_id}`
- Stream: `GET /api/v1/jobs/{job_id}/events` (SSE)
- Download generated artifact: `GET /api/v1/jobs/{job_id}/file`

## Tests

```bash
cd backend
pytest
```

Included tests:

- validation rules
- OneMap client (mocked behavior)
- VRPTW synthetic feasibility
- API smoke flow (upload -> geocode -> optimize -> results -> exports)

## Screenshot Instructions

Use these placeholders in your report/docs:

- `docs/screenshots/upload-validation.png`
- `docs/screenshots/geocoding-split-view.png`
- `docs/screenshots/optimization-infeasible-suggestions.png`
- `docs/screenshots/results-planner-view.png`
- `docs/screenshots/results-driver-view-mobile.png`
- `docs/screenshots/exports-tab.png`

Quick capture flow:

1. Start backend + frontend.
2. Open the target page in Chrome.
3. Press `F12` -> Device Toolbar (`Ctrl+Shift+M`) for mobile captures.
4. Use command menu `Ctrl+Shift+P` -> `Capture full size screenshot`.
5. Save under `docs/screenshots/` with names above.
