# Next Chat Handoff Context (SG-Route-OPT)

## Snapshot
- Repo: `c:\Users\User\OneDrive\Documents\FYP Documents\SG-Route-OPT`
- Branch: `main` (tracking `origin/main`)
- Date: 2026-02-16
- Status: feature integration completed locally; backend/frontend validation done; cloud deploy blocked by missing auth/env setup.

## Major Implementation State
This branch now includes:
- Async optimize orchestration via pipeline jobs:
  - `POST /api/v1/jobs/optimize`
  - `POST /tasks/handle`
  - Steps: `GEOCODE -> BUILD_MATRIX -> OPTIMIZE -> GENERATE_EXPORTS`
  - Job progress fields (`current_step`, `progress_pct`) and step state tracking.
- Matrix artifact split for async optimization stages.
- MLOps additions:
  - Config endpoints (`GET/POST /api/v1/ml/config`)
  - Drift report endpoint (`POST /api/v1/ml/drift-report`)
  - Vertex optional training endpoint (`POST /api/v1/ml/models/train/vertex`)
  - Versioned local artifacts and rollout/canary handling.
- Results UI updates:
  - Drag-and-drop resequencing with preview/revert/apply.
  - Violation badges and tooltips.
  - Makespan + sum-duration summaries in UI.
- Driver outputs:
  - Static map generation path integrated into exports.
  - Driver PDF generation and retrieval flow.
- Phone handling:
  - SG normalization/validation.
  - Driver call action remains `tel:` only; call button gated to valid phone.
- GCP scripts:
  - `infra/gcp/deploy.sh`
  - `infra/gcp/teardown.sh`

## Additional Fixes Done In This Session
1. SQLite lock resilience for async job progress updates:
   - File: `backend/app/services/job_pipeline.py`
   - Change: retry + tolerate lock contention when writing progress, so pipeline steps do not fail under local SQLite write contention.

2. ML model version collision fix for rapid consecutive training jobs:
   - File: `backend/app/services/ml_ops.py`
   - Change: model version now includes microseconds (`v%Y%m%d%H%M%S%f`) to avoid unique key collisions on `models.version`.

3. Dependency pin compatibility fix:
   - File: `backend/requirements.txt`
   - Updated:
     - `google-cloud-tasks==2.21.0`
     - `google-cloud-aiplatform==1.130.0`
   - Reason: resolve incompatibility with `ortools==9.14.6206` and protobuf constraints.

4. Local/legacy path hygiene:
   - File: `.gitignore`
   - Added ignores: `.venv-backend/`, `backend/app/ml/artifacts/`, `app/`, `src/`, `smoke_report.json`.

## Validation Results (Local)
### Backend tests
- Command: `py -m pytest -q backend/app/tests`
- Result: `19 passed`

### Frontend checks
- `npm test` in `frontend/`: pass
- `npm run build` in `frontend/`: pass

### Smoke flow
Executed local end-to-end smoke flow and wrote report at:
- `smoke_report.json` (ignored in git)

Confirmed:
- Upload -> geocode -> optimize pipeline succeeds from `/api/v1/jobs/optimize`.
- Step progression observed through all 4 stages with monotonic `progress_pct`.
- Resequence preview/apply/revert behavior correct.
- Valid SG phone normalized to E.164; invalid phone rejected; UI call button logic compatible.
- Makespan and sum durations available in results summary.
- Map PNG and PDF generation/retrieval work locally.
- ML model listing + canary config endpoints verified after local training.

## Cloud Deployment Status
### Current blocker
Cloud deployment is not complete from this machine because:
1. No authenticated gcloud account:
   - `gcloud auth list` => `No credentialed accounts.`
2. Required deploy env vars not set in shell:
   - `GCP_PROJECT_ID`
   - `GCP_REGION`
   - `GCS_BUCKET`
   - `MAPS_STATIC_API_KEY`
   - `ONEMAP_EMAIL`
   - `ONEMAP_PASSWORD`
   - `CLOUD_TASKS_QUEUE`
   - `SCHEDULER_TOKEN` (optional in script, but needed if enforcing scheduler token checks)

### What is already verified in code/scripts
- Cloud Run deploy config includes `--min-instances=0` and `--max-instances=1`.
- Cloud Tasks queue is created/updated with single-dispatch throttling.
- Weekly scheduler drift job is configured.
- `/tasks/handle` includes OIDC header/token validation path.

## Exact Resume Steps For Next Chat
1. Authenticate:
   - `gcloud auth login`
   - `gcloud config set project <YOUR_PROJECT_ID>`
2. Export env vars in shell (do not paste secrets into chat):
   - `GCP_PROJECT_ID`, `GCP_REGION`, `GCS_BUCKET`, `ONEMAP_EMAIL`, `ONEMAP_PASSWORD`, `MAPS_STATIC_API_KEY`
   - Optional/expected: `CLOUD_TASKS_QUEUE`, `SCHEDULER_TOKEN`
3. Run deploy:
   - `infra/gcp/deploy.sh` (via bash)
4. Verify runtime in GCP:
   - Cloud Run service settings (`min=0`, `max=1`)
   - Cloud Tasks queue throttling (`max-concurrent-dispatches=1`, `max-dispatches-per-second=1`)
   - Scheduler job exists and targets drift endpoint
   - `/tasks/handle` receives OIDC-authenticated task requests
5. Run final acceptance check against:
   - Job progression UI fields
   - Resequence preview/revert/apply
   - Phone-call button gating (`tel:` only)
   - Makespan/sum duration UI values
   - Static map correctness
   - PDF clarity + signed URL retrieval (should be present with GCS enabled)
   - Canary config + model listing endpoints

## Notes
- `frontend/tsconfig.tsbuildinfo` is modified by build and currently left uncommitted intentionally.
- Legacy directories `app/` and `src/` should remain uncommitted.
