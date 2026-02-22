# SG Route Optimization MVP

Local full-stack MVP for upload -> validate -> geocode -> optimize VRPTW -> interactive resequence -> visualize routes -> export driver artifacts (CSV/PDF/static maps) with async job orchestration.

Architecture diagrams and gap-closure roadmap: `ARCHITECTURE.md`

## About Project

SG Route Optimization is an end-to-end logistics planning system focused on Singapore route operations. The project combines operational planning workflows (upload, validation, geocoding, optimization, and execution-ready exports) with practical MLOps controls so planners can run, monitor, and continuously improve route quality from one web app.

Core outcomes:

- Reduce manual route planning effort with VRPTW optimization.
- Keep planner control through resequencing and constraint visibility.
- Generate driver-ready artifacts (PDF + map) from the same planning flow.
- Support production cloud deployment with async jobs, queue auth, and monitoring.

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
- Cache/Queue: Redis + RQ for local async workers; Cloud Tasks for cloud async jobs (geocode/optimize/export/ML)
- Static map rendering: Google Static Maps API (preferred) with Playwright/fallback renderer when key is absent
- Frontend: React + Vite + TypeScript + React-Leaflet
- External APIs: OneMap Search + OneMap Routing (mock mode if creds missing), optional Google Routes traffic-aware ETA

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

Core env vars:

- `GCP_PROJECT_ID`
- `GCP_REGION` (default `asia-southeast1`)
- `GCS_BUCKET` (for example `gs://route_app`)
- `MAPS_STATIC_API_KEY`
- `ONEMAP_EMAIL`
- `ONEMAP_PASSWORD`
- `FEATURE_GOOGLE_TRAFFIC` (`true`/`false`, default `false`)
- `FEATURE_ML_UPLIFT` (`true`/`false`, default `false`)
- `FEATURE_EVAL_DASHBOARD` (`true`/`false`, default `false`)
- `GOOGLE_ROUTES_API_KEY` (server-side only; preferred)
- `GOOGLE_MAPS_API_KEY` (legacy alias; server-side only)
- `GOOGLE_ROUTES_REGION` (label/config, default `asia-southeast1`)
- `GOOGLE_ROUTING_PREFERENCE` (`TRAFFIC_AWARE` or `TRAFFIC_AWARE_OPTIMAL`)
- `GOOGLE_MATRIX_MAX_ELEMENTS` (default `25`, matrix guardrail)
- `GOOGLE_CACHE_TTL_SECONDS` (default `600`)
- `GOOGLE_TRAFFIC_MODE` (legacy alias for routing preference)
- `GOOGLE_MAX_ELEMENTS_PER_JOB` (legacy alias for matrix cap)
- `GOOGLE_TIMEOUT_SECONDS` (default `20`)
- `GOOGLE_RATE_LIMIT_QPS` (default `5`)

ML and rollout options:

- `FEATURE_VERTEX_AI` (`true`/`false`, default `false`)
- `VERTEX_MODEL_DISPLAY_NAME` (default `route-time-regressor`)
- `ML_DRIFT_THRESHOLD`
- `ML_RETRAIN_MIN_ROWS`

Queue/scheduler/security options:

- `CLOUD_TASKS_QUEUE` (default `route-jobs`)
- `CLOUD_TASKS_SERVICE_ACCOUNT` (used for OIDC on `/tasks/handle`)
- `CLOUD_TASKS_AUDIENCE` (optional, defaults to `${APP_BASE_URL}/tasks/handle`)
- `API_SERVICE_ACCOUNT_EMAIL` (service account email used for IAM signed URL fallback in Cloud Run)
- `TASKS_AUTH_REQUIRED` (default `true`)
- `SCHEDULER_TOKEN` (required in `prod`/`production`; shared secret for `/api/v1/ml/drift-report`)

General runtime options:

- `REDIS_URL` (default `redis://redis:6379/0`)
- `DATABASE_URL` (default `sqlite:///./app.db`; for cloud use Postgres, e.g. `postgresql+psycopg://...`)
- `ALLOWED_ORIGINS` (default `http://localhost:5173`)
- `APP_BASE_URL` (default `http://localhost:8000`)
- `FRONTEND_BASE_URL` (default `http://localhost:5173`)
- `JOBS_FORCE_INLINE` (set `true` for local/test to execute queued steps inline)
- `SIGNED_URL_TTL_SECONDS` (default `3600`)
- `OPTIMIZE_LATENCY_WARN_SECONDS` (default `1200`, emits slow-optimize warning log marker for alerting)
- `OPTIMIZE_MAX_STOPS` (default `80`, tuned for single-instance cloud profile; rejects oversized optimize/ab-test requests early)
- `OPTIMIZE_MAX_MATRIX_ELEMENTS` (default `6500`, tuned O(N^2) cap; rejects requests with infeasible matrix size early)

If OneMap credentials are empty, backend automatically uses deterministic mock geocoding/routing for local development.

## Local Run

### Backend

```bash
cd backend
python -m pip install -r requirements.txt
python -m alembic -c alembic.ini upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

If you already have a legacy local SQLite DB created before Alembic was added, stamp it once before upgrading:

```bash
cd backend
python -m alembic -c alembic.ini stamp 4a6adfe08937
python -m alembic -c alembic.ini upgrade head
```

### Worker (for async queue)

```bash
cd backend
rq worker default --url redis://localhost:6379/0
```

Queue behavior:
- Local mode (`APP_ENV=dev`): async jobs are queued to Redis/RQ.
- Cloud mode (`APP_ENV=prod`/`staging`): async jobs are queued to Cloud Tasks.
- `JOBS_FORCE_INLINE=true` is only for tests/dev overrides.

### Frontend

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Open: `http://localhost:5173`

## GCP Deployment (Cloud Run + Cloud Tasks)

Scripts:

- Deploy: `infra/gcp/deploy.sh`
- Deploy frontend (bash): `infra/gcp/deploy_frontend.sh`
- Deploy frontend (PowerShell): `infra/gcp/deploy_frontend.ps1`
- Teardown: `infra/gcp/teardown.sh`

Deploy example:

```bash
export GCP_PROJECT_ID=gen-lang-client-0328386378
export GCP_REGION=asia-southeast1
export GCS_BUCKET=gs://route_app
export MAPS_STATIC_API_KEY=your_key
export ONEMAP_EMAIL=your_email
export ONEMAP_PASSWORD=your_password
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME'
export FEATURE_VERTEX_AI=false

bash infra/gcp/deploy.sh
```

`infra/gcp/deploy.sh` binds `DATABASE_URL` from Secret Manager into Cloud Run. On first deploy, provide `DATABASE_URL` to seed the secret version.

`infra/gcp/deploy.sh` now runs `alembic upgrade head` via a Cloud Run Job before deploying the service revision.
Controls:

- `RUN_DB_MIGRATIONS=true|false` (default `true`)
- `MIGRATION_JOB_NAME` (default `${SERVICE_NAME}-db-migrate`)
- `RUN_PHASE7_MONITORING=true|false` (default `false`; apply Phase 7 alerts + dashboard)
- `MONITORING_NOTIFICATION_CHANNELS` (optional comma-separated channel IDs for policy notifications)

Frontend deploy example (production static build):

```powershell
$env:GCP_PROJECT_ID="gen-lang-client-0328386378"
$env:GCP_REGION="asia-southeast1"
powershell -NoProfile -ExecutionPolicy Bypass -File infra/gcp/deploy_frontend.ps1
```

or:

```bash
export GCP_PROJECT_ID=gen-lang-client-0328386378
export GCP_REGION=asia-southeast1
bash infra/gcp/deploy_frontend.sh
```

Guardrails baked in:

- Cloud Run `min-instances=0`, `max-instances=1`
- Cloud Tasks queue throttled (`max-concurrent-dispatches=1`)
- Cloud mode does not require Redis worker processes for async job execution
- Weekly Cloud Scheduler trigger for `/api/v1/ml/drift-report`
- Cloud Run startup probe on `/health/ready` and liveness probe on `/health/live`
- Cloud Tasks OIDC callback path validated with production payload format (`/tasks/handle` 2xx)
- Signed URL generation for export artifacts hardened for Cloud Run service-account credentials

Monitoring/alerting:

- Policy file: `infra/gcp/monitoring/cloud_run_sg_route_opt_5xx_error_rate_policy.json`
- Active policy: `Cloud Run sg-route-opt-api - 5xx Error Rate > 5%`
- Created as: `projects/gen-lang-client-0328386378/alertPolicies/4637109870947199083`

Phase 7 observability assets:

- Apply script: `infra/gcp/monitoring/apply_phase7_monitoring.sh`
- Alert templates: `infra/gcp/monitoring/phase7/alert_policies/*.json`
- Dashboard template: `infra/gcp/monitoring/phase7/dashboard/sg_route_opt_core_slo_dashboard.json`

Phase 7 signals covered:

- stuck jobs (Cloud Tasks queue depth + stale lock reclaim events)
- Cloud Tasks retry age and failure attempt rate
- DB lock retry spikes (`DB_LOCK_RETRY`)
- fallback event rate spikes (Google/OneMap fallbacks)
- signed URL failures
- slow optimize runs (`OPTIMIZE_LATENCY_SLOW`)

## Current Production Snapshot (February 18, 2026)

- Project: `gen-lang-client-0328386378`
- Region: `asia-southeast1`
- Cloud Run service: `sg-route-opt-api`
- URL: `https://sg-route-opt-api-7wgewdyenq-as.a.run.app`
- Frontend service: `sg-route-opt-web`
- Webapp URL: `https://sg-route-opt-web-7wgewdyenq-as.a.run.app`
- Latest API revision: `sg-route-opt-api-00028-7df`
- Latest frontend revision: `sg-route-opt-web-00003-hp4`
- Queue: `routeapp-queue`
- Scheduler job: `route-ml-drift-weekly`
- Custom domains:
  - `https://app.sgroute.com`
  - `https://api.sgroute.com`
- Domain mapping status:
  - `app.sgroute.com` -> `True`
  - `api.sgroute.com` -> `True`
- Health endpoint: `GET /api/v1/health` returns `200` with `env=prod` and traffic/uplift/eval feature flags
- Probe endpoints:
  - `GET /health/live` (liveness)
  - `GET /health/ready` (readiness + dependency checks)
- OneMap secrets are now provisioned in Secret Manager:
  - `ONEMAP_EMAIL` (version `1`)
  - `ONEMAP_PASSWORD` (version `1`)
- Google traffic verification:
  - `use_live_traffic=true` optimize requests return `eta_source=google_traffic`
  - `traffic_timestamp` is non-null for live-traffic plans
  - No recent `Google ETA fallback activated` logs on revision `sg-route-opt-api-00028-7df` during smoke checks

## Operations Notes

- GCP Resource Manager tag binding (`environment`) requires org-level IAM permissions (`resourcemanager.tagKeys.create` and `resourcemanager.tagValueBindings.create`).
- If you want to enforce org tags from this project, run it using an org admin account or pre-create the tag key/value centrally, then bind it to:
  - `//cloudresourcemanager.googleapis.com/projects/858316205970`

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
- Optional toggle: `Use live traffic (Google)` (shown only when backend feature flag is enabled)
- Run optimization (background pipeline job with steps: `GEOCODE -> BUILD_MATRIX -> OPTIMIZE -> GENERATE_EXPORTS`)
- If infeasible, apply suggestion chips and rerun
- Watch solver/matrix progress and resume after navigation
- Run A/B simulation mode (baseline fallback vs ML-enhanced travel times)
- Download A/B report package (CSV + plot + JSON)

5. Results (`/results`)
- Planner View: map + route cards + stop sequence
- ETA source badge: `Google traffic / ML uplift / ML baseline / OneMap`
- Traffic timestamp shown when Google traffic ETAs are used
- Non-blocking warning when Google traffic falls back to baseline ETAs
- Planner Edit Mode: drag-drop stop resequencing + ETA recompute + violations
- Driver View: mobile-friendly route sheet (large text/tap targets)
- Exports tab: PDF/CSV outputs

6. Evaluation (`/evaluation`, feature-flagged)
- Prediction-level metrics: compare `static_duration` baseline vs `ML uplift` against Google traffic reference samples
- Planning-level metrics: compare baseline vs ML uplift plans under Google-reference simulation
- KPI report package download (JSON + CSV in ZIP)

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
- Phone actions are direct `tel:` links only (no Twilio dependency)

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

### Sample Data Pack

Ready-to-use datasets are in `sample_data/`:

- `sample_data/stops_valid_small.csv` (12-stop clean dataset)
- `sample_data/stops_valid_30.csv` (30-stop valid dataset)
- `sample_data/stops_mixed_invalid.csv` (intentional validation failures)
- `sample_data/README.md` (quick test flow)

## API Endpoints

- `POST /api/v1/datasets/upload`
- `GET /api/v1/datasets/{dataset_id}`
- `GET /api/v1/datasets/{dataset_id}/stops?status=...`
- `POST /api/v1/datasets/{dataset_id}/geocode?failed_only=true|false`
- `POST /api/v1/stops/{stop_id}/geocode/manual`
- `POST /api/v1/datasets/{dataset_id}/optimize`
- `POST /api/v1/datasets/{dataset_id}/optimize/ab-test`
- `POST /api/v1/jobs/optimize`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/events`
- `GET /api/v1/jobs/{job_id}/file`
- `POST /tasks/handle` (Cloud Tasks worker callback with OIDC auth)
- `GET /api/v1/plans/{plan_id}`
- `POST /api/v1/plans/{plan_id}/routes/{route_id}/resequence`
- `GET /api/v1/plans/{plan_id}/export?format=csv|pdf`
- `POST /api/v1/plans/{plan_id}/export?format=pdf`
- `GET /api/v1/plans/{plan_id}/export/driver-csv`
- `GET /api/v1/plans/{plan_id}/map-snapshot`
- `GET /api/v1/plans/{plan_id}/map.png`
- `POST /api/v1/plans/{plan_id}/map.png`
- `GET /api/v1/ml/models`
- `GET /api/v1/ml/config`
- `POST /api/v1/ml/config`
- `POST /api/v1/ml/models/train`
- `POST /api/v1/ml/models/train/vertex`
- `POST /api/v1/ml/rollout`
- `POST /api/v1/ml/actuals/upload`
- `GET /api/v1/ml/metrics/latest`
- `POST /api/v1/ml/drift-report`
- `GET /api/v1/ml/evaluation/compare`
- `POST /api/v1/ml/evaluation/run`
- `GET /api/v1/health`
- `GET /health/live`
- `GET /health/ready`

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
    "solver": {"solver_time_limit_s": 15, "allow_drop_visits": true},
    "use_live_traffic": true
  }'
# => { "job_id": "...", ... }
curl "http://localhost:8000/api/v1/jobs/<job_id>"
```

### Start Optimize Pipeline via Jobs API

```bash
curl -X POST "http://localhost:8000/api/v1/jobs/optimize" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": 1,
    "depot_lat": 1.3521,
    "depot_lon": 103.8198,
    "fleet_config": {"num_vehicles": 2, "capacity": 25},
    "workday_start": "08:00",
    "workday_end": "18:00",
    "solver": {"solver_time_limit_s": 20, "allow_drop_visits": true},
    "use_live_traffic": true
  }'
```

## Google Traffic Awareness

Enable traffic-aware ETAs (server-side only):

```bash
export FEATURE_GOOGLE_TRAFFIC=true
export GOOGLE_ROUTES_API_KEY=your_server_side_key
export GOOGLE_ROUTING_PREFERENCE=TRAFFIC_AWARE
```

Recommended API key restrictions:

- Restrict key to **Routes API** only.
- Restrict by service account/IP/network perimeter where possible.
- Do not expose Google API keys to frontend env vars.

Demo script:

1. Turn `Use live traffic (Google)` ON in `/optimization` and run optimize.
2. Open `/results` and confirm badge shows `ETA source: Google traffic`.
3. Turn toggle OFF, rerun optimize, confirm badge changes to baseline source.
4. Simulate quota/timeout and verify non-blocking fallback warning appears.

Operational notes:

- If secret values are edited manually, avoid trailing whitespace/newline in `GOOGLE_ROUTES_API_KEY`.
- Fallback logs now include structured `details=` payload to speed up runtime diagnosis:
  - `Google ETA fallback activated (..., details=...)`
  - `Google resequence fallback activated (..., details=...)`
  - `Google Routes request error after retries (details=...)`

### Optimize A/B Simulation (Baseline vs ML)

```bash
curl -X POST "http://localhost:8000/api/v1/datasets/1/optimize/ab-test" \
  -H "Content-Type: application/json" \
  -d '{
    "depot_lat": 1.3521,
    "depot_lon": 103.8198,
    "fleet": {"num_vehicles": 2, "capacity": 25},
    "workday_start": "08:00",
    "workday_end": "18:00",
    "solver": {"solver_time_limit_s": 15, "allow_drop_visits": true},
    "model_version": null
  }'
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
- Baseline vs ML formal evaluation (`GET /api/v1/ml/evaluation/compare`)
- Evaluation report package generation (`POST /api/v1/ml/evaluation/run`)
- Daily monitoring + weekly retrain-if-needed scheduler (backend startup)

Evaluation dashboard page: `/evaluation` (requires `FEATURE_EVAL_DASHBOARD=true`)

API endpoints:

- `GET /api/v1/evaluation/prediction?limit=5000`
- `POST /api/v1/evaluation/run`

### Formal Evaluation KPIs

The evaluation pipeline compares fallback baseline vs selected ML model across:

- `MAE (s)`
- `MAPE (%)`
- `RMSE (s)`
- `P90 Absolute Error (s)`
- `Within 15% Error Rate`

It also outputs segmented metrics (`peak/off-peak`, `short/long haul`) and uncertainty-aware prediction samples.

### Baseline vs ML Compare

```bash
curl "http://localhost:8000/api/v1/ml/evaluation/compare?days=30&limit=5000"
```

### Generate Evaluation Report Package

```bash
curl -X POST "http://localhost:8000/api/v1/ml/evaluation/run" \
  -H "Content-Type: application/json" \
  -d '{"days":30,"limit":5000,"model_version":null}'
```

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
Each run writes:

- `model.pkl`
- `metrics.json`
- `feature_schema.json`
- `version.txt`

### ML Uplift Data + Training Scripts

Collect cost-aware Google samples:

```bash
cd backend
python -m ml_uplift.collect_samples --dataset-id 1 --sample-elements 25
```

Train uplift model:

```bash
cd backend
python -m ml_uplift.train --min-rows 120
```

Uplift samples are stored at `backend/data/ml_uplift/samples.csv`.
Uplift artifacts are stored at `backend/app/ml_uplift/artifacts/`.

## Interview Demo Checklist

1. Upload + validate
- Upload `sample_stops.csv`
- Show partial/valid summary and optional `phone`/`contact_name` handling

2. Async optimize pipeline
- Start optimization from `/optimization`
- Open job status and show step progression: `GEOCODE`, `BUILD_MATRIX`, `OPTIMIZE`, `GENERATE_EXPORTS`
- Confirm UI only marks workflow stage complete after success

3. Planner resequencing
- Go to `/results` -> Planner View -> `Edit mode`
- Drag/drop route stops with `dnd-kit`
- Click `Recompute ETAs`
- Show violation badges + tooltip details, then `Revert` and `Apply changes`

4. Driver clarity + phone support
- Open Driver View
- Show `Navigate`, `Copy address`, and `Call` button via `tel:` link (only appears for valid phone)

5. Static maps + PDF pack
- Open Exports tab and generate PDF
- Show route map PNG and driver pack output
- Mention GCS paths:
  - `maps/{plan_id}/{route_id}.png`
  - `driver_packs/{plan_id}/driver_pack.pdf`
  - `matrix/{job_id}.json` (BUILD_MATRIX -> OPTIMIZE durable handoff artifact)

6. MLOps
- Open `/ml`
- Show model registry, rollout config, canary settings, and drift metrics
- Run baseline vs ML evaluation and download report package

7. ML Uplift Proof Page
- Open `/evaluation`
- Run evaluation for the current dataset
- Show prediction-level MAE/MAPE delta and planning-level late stops/overtime delta
- Download ZIP report and quote the summary sentence in slides/report

### View Job Progress

- Poll: `GET /api/v1/jobs/{job_id}`
- Stream: `GET /api/v1/jobs/{job_id}/events` (SSE)
- Download generated artifact: `GET /api/v1/jobs/{job_id}/file`
- Job payload includes `progress_pct`, `current_step`, step state map, and error metadata (`error_code`, `error_detail`).

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
