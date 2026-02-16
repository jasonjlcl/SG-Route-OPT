# Next Chat Context (SG-Route-OPT)

## Current Snapshot
- Repo: `c:\Users\User\OneDrive\Documents\FYP Documents\SG-Route-OPT`
- Branch: `main` (tracking `origin/main`)
- Latest pushed commits:
  - `9feb1b7` - major async pipeline/MLOps/UI/infra integration
  - `9df01b2` - Cloud Run startup + deploy script hardening
- Remote: `origin/main` contains both commits

## What Is Implemented
- Async optimize pipeline:
  - `POST /api/v1/jobs/optimize`
  - `POST /tasks/handle`
  - Step chain: `GEOCODE -> BUILD_MATRIX -> OPTIMIZE -> GENERATE_EXPORTS`
  - Job fields: `current_step`, `progress_pct`, `steps`, `error_code`, `error_detail`
- MLOps:
  - `GET/POST /api/v1/ml/config`
  - `POST /api/v1/ml/drift-report`
  - `POST /api/v1/ml/models/train/vertex`
  - Model versioning + rollout/canary support
- Results UI:
  - Resequence preview/revert/apply
  - Violation badges/tooltips
  - Makespan + sum-duration summary
- Phone:
  - SG validation/normalization
  - Driver call action is `tel:` only
- Export:
  - Static map + driver PDF flow integrated
- GCP scripts:
  - `infra/gcp/deploy.sh`
  - `infra/gcp/teardown.sh`

## Key Fixes Added During Validation
- `backend/app/services/job_pipeline.py`:
  - SQLite lock tolerance for progress updates in local/test mode.
- `backend/app/services/ml_ops.py`:
  - Model version now uses microseconds (`v%Y%m%d%H%M%S%f`) to prevent collisions.
- `backend/requirements.txt`:
  - `google-cloud-tasks==2.21.0`
  - `google-cloud-aiplatform==1.130.0`
- `backend/Dockerfile`:
  - Uses `${PORT}` and removes `--reload` for Cloud Run compatibility.
- `infra/gcp/deploy.sh`:
  - Conditional secret bindings
  - `gcloud storage` bucket ops
  - Windows/Git-Bash-safe adjustments
  - Temp root `Dockerfile` handling for Cloud Build context
  - glob-safe scheduler command handling (`set -f`)

## Local Validation Status
- Backend tests: `py -m pytest -q backend/app/tests` => pass (`19 passed`)
- Frontend tests/build: pass
- Smoke flow validated:
  - Upload -> geocode -> optimize via jobs API
  - Step progression and monotonic progress
  - Resequence preview/apply/revert
  - Phone visibility logic
  - Map PNG and PDF generation
  - ML model listing + canary config endpoints

## Cloud Deployment Status (Live)
Project: `gen-lang-client-0328386378`
Region: `asia-southeast1`
Service: `sg-route-opt-api`
URL: `https://sg-route-opt-api-7wgewdyenq-as.a.run.app`
Queue: `routeapp-queue`
Scheduler job: `route-ml-drift-weekly`

### Confirmed
- Cloud Run deployed and serving traffic.
- Cloud Run scaling:
  - `maxScale=1`
  - `minScale` unset (effective `0`)
- Cloud Tasks queue throttling:
  - `maxConcurrentDispatches=1`
  - `maxDispatchesPerSecond=1`
- Scheduler weekly job exists with OIDC service account.
- `/tasks/handle` enforces auth:
  - unauthenticated request returned `401`
  - Cloud Tasks requests reached endpoint with `Google-Cloud-Tasks` user-agent

### Observed in logs
- `/tasks/handle` from test tasks currently returned `422` (payload/content mismatch in manual probe), but auth path is active.
- `/api/v1/health` currently returns `500` in deployed env and needs investigation from logs/DB/runtime config.

## Secret Manager State
- `MAPS_STATIC_API_KEY` has versions created.
- `ONEMAP_EMAIL` and `ONEMAP_PASSWORD` secrets were created, but no value versions were added in this session.
  - Add values if real OneMap calls are required.

## Open Follow-ups for Next Chat
1. Investigate and fix Cloud Run `/api/v1/health` returning `500`.
2. Add `ONEMAP_EMAIL` + `ONEMAP_PASSWORD` secret versions (if not using mock behavior).
3. Validate a real optimize job through deployed service URL:
   - upload dataset
   - trigger `/api/v1/jobs/optimize`
   - confirm full step completion and export artifacts
4. Validate Cloud Tasks callback end-to-end with production payload format (expect 2xx, not 422).
5. Optional: set `SCHEDULER_TOKEN` and decide whether drift endpoint should enforce it in prod scheduler calls.

## Working Tree Note
- Local uncommitted generated file: `frontend/tsconfig.tsbuildinfo`.
