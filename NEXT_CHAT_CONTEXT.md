# Next Chat Context (SG-Route-OPT)

## Current Snapshot (As Of February 16, 2026)
- Repo: `c:\Users\User\OneDrive\Documents\FYP Documents\SG-Route-OPT`
- Branch: `main` (tracking `origin/main`)
- Remote: `origin` -> `https://github.com/jasonjlcl/SG-Route-OPT.git`
- Latest pushed cloud-fix commits:
  - `fa5b46e` - fix `/api/v1/health` response validation failure
  - `1559d0a` - cloud signing/deploy env hardening
  - `a58638b` - Cloud Tasks OIDC act-as IAM + fallback logging
  - `1341d23` - scoped token for IAM signed URLs
  - `1a18553` - explicit API service account email for signing fallback

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
  - GCS upload + signed URL generation in Cloud Run via IAM fallback
- GCP scripts:
  - `infra/gcp/deploy.sh`
  - `infra/gcp/teardown.sh`

## Cloud Hardening Added
- Health endpoint fix:
  - `backend/app/api/health.py` response type corrected to prevent `ResponseValidationError` 500.
- Deploy script fixes:
  - `infra/gcp/deploy.sh` uses `--update-env-vars` (prevents wiping runtime env vars).
  - Added IAM bindings for:
    - `roles/iam.serviceAccountTokenCreator` on API SA
    - `roles/iam.serviceAccountUser` on Tasks SA for API SA
  - Added `API_SERVICE_ACCOUNT_EMAIL` env var injection.
- Cloud Tasks robustness:
  - `backend/app/services/cloud_tasks.py` now logs enqueue fallback reason.
- Signed URL robustness:
  - `backend/app/services/storage.py` falls back to IAM signing with scoped credentials.
  - Uses configured `API_SERVICE_ACCOUNT_EMAIL` when metadata credential email is `default`.

## Local Validation Status
- Backend tests: `.\.venv\Scripts\python.exe -m pytest -q backend/app/tests` => pass (`21 passed`)
- Frontend tests/build: previously validated pass

## Cloud Deployment Status (Live)
Project: `gen-lang-client-0328386378`  
Region: `asia-southeast1`  
Service: `sg-route-opt-api`  
URL: `https://sg-route-opt-api-7wgewdyenq-as.a.run.app`  
Queue: `routeapp-queue`  
Scheduler job: `route-ml-drift-weekly`  
Latest revision: `sg-route-opt-api-00015-njj`

### Confirmed
- `GET /api/v1/health` => `200` with `env=prod`
- Cloud Run scaling:
  - `maxScale=1`
  - `minScale` unset (effective `0`)
- Cloud Tasks queue throttling:
  - `maxConcurrentDispatches=1`
  - `maxDispatchesPerSecond=1`
- Scheduler weekly job exists with OIDC service account
- `/tasks/handle` auth path active:
  - unauthenticated manual request => `401`
  - production-format Cloud Tasks callbacks => `200` (Google-Cloud-Tasks user-agent)
- Real optimize job validated end-to-end:
  - reached `SUCCEEDED`
  - exports generated
  - map/PDF signed URLs present

## Secret Manager State
- `MAPS_STATIC_API_KEY`: versions exist
- `ONEMAP_EMAIL`: secret exists, versions count = `0`
- `ONEMAP_PASSWORD`: secret exists, versions count = `0`

## Open Follow-ups
1. Add `ONEMAP_EMAIL` + `ONEMAP_PASSWORD` secret versions if real OneMap calls are required.
2. Decide whether to enforce `SCHEDULER_TOKEN` in production scheduler calls.
3. Optional platform hygiene: add GCP project `environment` tag (warning currently shown by gcloud).

## Working Tree Note
- Local uncommitted generated file: `frontend/tsconfig.tsbuildinfo`.
