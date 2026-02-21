# Next Chat Context (SG-Route-OPT)

## Timestamp
- Generated: February 21, 2026
- Purpose: handoff after completing Phase 1 (DB migration foundation + cloud DATABASE_URL secret wiring)

## Repo Snapshot
- Repo: `c:\Users\User\OneDrive\Documents\FYP Documents\SG-Route-OPT`
- Branch: `main`
- HEAD: `0ee2cd0`
- Remote: `https://github.com/jasonjlcl/SG-Route-OPT.git`

## What Was Completed In This Chat (Phase 1)

### 1) Alembic migration system added
- Added Alembic scaffolding:
  - `backend/alembic.ini`
  - `backend/alembic/env.py`
  - `backend/alembic/versions/4a6adfe08937_baseline_schema.py`
- Baseline revision ID: `4a6adfe08937`
- Alembic is configured to use `DATABASE_URL` from env when present.

### 2) Runtime schema mutation removed
- Removed startup schema creation/mutation path:
  - `backend/app/main.py`
  - `backend/app/utils/db.py`
- `Base.metadata.create_all(...)` and `ensure_schema_compatibility()` are no longer used.
- Schema is now intended to be managed by migrations.

### 3) Dependencies updated for migration + Postgres
- `backend/requirements.txt` updates:
  - `alembic==1.18.4`
  - `psycopg[binary]==3.2.12`

### 4) Cloud deploy script now supports DATABASE_URL secret binding
- Updated `infra/gcp/deploy.sh` to:
  - require or create secret `DATABASE_URL` (or custom `DATABASE_URL_SECRET_NAME`)
  - seed secret from env var `DATABASE_URL` on first deploy
  - fail early if secret has no versions
  - include `DATABASE_URL=...:latest` in Cloud Run `--set-secrets`

### 5) Dev docs/commands updated
- `README.md` now documents:
  - local migration command before backend start
  - Postgres DSN expectation for cloud
  - first deploy needs `DATABASE_URL` to seed secret
- `Makefile` now has:
  - `db-migrate` target (`cd backend && alembic -c alembic.ini upgrade head`)

## Validation Performed
- Passed: `alembic upgrade head` on temp SQLite DB.
- Passed: downgrade+upgrade cycle on temp SQLite DB.
- Passed: `py -3.10 -m compileall backend/app backend/alembic`.
- Note: pytest in current local `.venv` hit env/plugin issue (`ModuleNotFoundError: backports` from pytest plugin load).

## Current Working Tree (Uncommitted)
- Modified:
  - `Makefile`
  - `README.md`
  - `backend/app/main.py`
  - `backend/app/utils/db.py`
  - `backend/requirements.txt`
  - `infra/gcp/deploy.sh`
- New:
  - `backend/alembic.ini`
  - `backend/alembic/*`

## Important Notes
- Cloud SQL resource provisioning is NOT yet automated in `infra/gcp/deploy.sh`.
- Current Phase 1 result assumes Cloud SQL instance/database/user already exists and `DATABASE_URL` points to it.
- Existing unrelated dirty files should not be mass-reverted.

## Suggested Next Actions (Next Chat)
1. Run/install checks locally:
   - `cd backend`
   - `python -m pip install -r requirements.txt`
   - `python -m alembic -c alembic.ini upgrade head`
2. Validate app boot using migrated schema only.
3. Optionally add a deploy-safe migration execution step in CI/CD (pre-deploy or release job).
4. Continue with Phase 2 (artifact durability: move matrix handoff to GCS-backed loading path).

---

## Update (February 21, 2026 - Phase 2 + Validation)

### Completed In This Chat
1. Local setup and migration checks completed:
   - Installed backend dependencies with `py -3.11 -m pip install -r backend/requirements.txt`.
   - Existing `backend/app.db` had pre-Alembic tables, so baseline was stamped once:
     - `py -3.11 -m alembic -c alembic.ini stamp 4a6adfe08937`
   - Migration command now succeeds:
     - `py -3.11 -m alembic -c alembic.ini upgrade head`

2. App boot validated against migrated schema:
   - `GET /api/v1/health` returned `200` with `status=ok` via FastAPI TestClient startup flow.

3. Phase 2 implemented: durable matrix handoff via storage-backed loading path:
   - Added `download_bytes(object_path=...)` in `backend/app/services/storage.py`.
   - Updated optimize pipeline loading in `backend/app/services/job_pipeline.py`:
     - prefer `result_ref.matrix_artifact_ref.object_path` (GCS/local artifact store),
     - fallback to `result_ref.matrix_artifact_ref.file_path`,
     - fallback to legacy `result_ref.matrix_artifact_path`.

4. Deploy-safe migration step added:
   - `infra/gcp/deploy.sh` now runs `alembic -c alembic.ini upgrade head` through a Cloud Run Job before Cloud Run service deploy.
   - Controls:
     - `RUN_DB_MIGRATIONS` (default `true`)
     - `MIGRATION_JOB_NAME` (default `${SERVICE_NAME}-db-migrate`)

5. Tests added/updated:
   - New: `backend/app/tests/test_job_pipeline_matrix_artifact.py`
   - Updated: `backend/app/tests/test_storage.py` with `download_bytes` coverage.

### Validation Performed In This Chat
- Passed: `py -3.11 -m alembic -c alembic.ini upgrade head`
- Passed: health boot check (`/api/v1/health` => `200`, `status=ok`)
- Passed: `py -3.11 -m pytest backend/app/tests/test_storage.py backend/app/tests/test_job_pipeline_matrix_artifact.py` (`6 passed`)
- Passed: `py -3.11 -m pytest backend/app/tests/test_jobs.py` (`3 passed`)
- Passed: `py -3.11 -m compileall backend/app/services backend/app/tests`

### Updated Suggested Next Actions
1. Run a real GCP deploy dry run in target project to confirm `gcloud run jobs create/update/execute` behavior for the migration job.
2. Optionally add retention/cleanup policy for `matrix/{job_id}.json` artifacts in GCS.
3. Plan next phase after matrix durability (for example, Cloud SQL provisioning automation if still desired).

---

## Update (February 21, 2026 - Phase 3 Started: Job Orchestration Unification)

### Completed In This Chat
1. Unified async dispatch path:
   - Added queue-mode routing in `backend/app/services/cloud_tasks.py`:
     - cloud mode (`APP_ENV=prod|production|staging`) -> Cloud Tasks
     - local mode -> Redis/RQ
     - `JOBS_FORCE_INLINE=true` -> inline execution (test/dev override)
   - Removed daemon-thread fallback from cloud paths (Cloud Tasks enqueue failures now fail fast with structured `AppError`).

2. Unified task handler entrypoint:
   - `POST /tasks/handle` now dispatches both:
     - pipeline step tasks (`kind=pipeline_step`)
     - generic job tasks (`kind=job`)
   - Backward compatibility preserved for existing step payloads.

3. Generic job enqueue path switched to unified dispatcher:
   - `backend/app/services/jobs.py` now enqueues via `enqueue_job_task(...)`.
   - Added `run_queued_job(job_id)` for shared execution from both Cloud Tasks and RQ worker paths.

4. Settings support:
   - Added `Settings.is_cloud_mode` in `backend/app/utils/settings.py`.

5. Documentation update:
   - README now states explicit queue behavior by mode (local RQ vs cloud Cloud Tasks).

### Validation Performed In This Chat
- Passed: `py -3.11 -m pytest backend/app/tests/test_queue_orchestration.py backend/app/tests/test_jobs.py backend/app/tests/test_api_smoke.py backend/app/tests/test_ml_uplift_and_evaluation.py` (`13 passed`)
- Passed: `py -3.11 -m compileall backend/app/services backend/app/api backend/app/tests`

### Remaining For Phase 3 Completion
1. Cloud environment dry run with real GCP settings to validate end-to-end:
   - geocode/optimize/export/ML jobs enqueue and execute through Cloud Tasks without Redis.
2. Optional: add explicit deploy-time warning if Redis config is set in cloud mode (for operator clarity).

---

## Update (February 21, 2026 - Phase 4 Completed: Pipeline Correctness)

### Completed In This Chat
1. Step lease timeout + stale-lock reclaim:
   - Added lease handling to step locks in `backend/app/services/jobs.py`:
     - `lease_expires_at` metadata
     - stale `RUNNING` step reclaim in `lock_step(...)`
     - configurable lease via `PIPELINE_STEP_LEASE_SECONDS` (`backend/app/utils/settings.py`)

2. Idempotent re-entry behavior:
   - Pipeline progress updates now refresh step lease (`touch_step_lease(...)`).
   - Merge/complete now require active lock ownership (`has_step_lock(...)`) to prevent stale worker writes.
   - Final-step redelivery now finalizes job to `SUCCEEDED` when step already `SUCCEEDED` but job status is not terminal.

3. Staging crash/retry drill executed (Cloud Tasks redelivery + delayed handler):
   - Temporary drill knobs added:
     - `PIPELINE_RETRY_DRILL_STEP`
     - `PIPELINE_RETRY_DRILL_DELAY_SECONDS`
   - Drill run confirmed:
     - `/tasks/handle` had a `500` attempt followed by retries and success
     - optimize job completed `SUCCEEDED`
     - `steps.BUILD_MATRIX.stale_reclaimed = 1` observed in job payload
   - Staging cleanup done after drill (drill env vars removed).

### Validation Performed In This Chat
- Passed: `py -3.11 -m pytest backend/app/tests/test_pipeline_stale_lock.py backend/app/tests/test_queue_orchestration.py backend/app/tests/test_jobs.py` (`12 passed`)
- Passed: staging drill end-to-end with Cloud Tasks retry and stale-lock reclaim evidence.

---

## Update (February 21, 2026 - Phase 5 In Progress: Health + Security Hardening)

### Completed In This Chat
1. Health endpoints:
   - Added `GET /health/live` and `GET /health/ready` in `backend/app/api/health.py`.
   - Readiness checks now include:
     - DB connectivity (`SELECT 1`)
     - Cloud Tasks queue reachability (in cloud mode)
     - GCS bucket reachability (in cloud mode)
   - Kept backward-compatible `GET /api/v1/health`.

2. Secret normalization + required-secret validation in production:
   - Added normalization validators for string/secret env vars in `backend/app/utils/settings.py`.
   - Added production validation guardrails:
     - reject SQLite `DATABASE_URL` in prod
     - require non-empty `SCHEDULER_TOKEN`
     - require cloud/task/bucket and OneMap credentials in prod
     - require `TASKS_AUTH_REQUIRED=true` in prod

3. Drift endpoint hardening:
   - `backend/app/api/ml.py` now requires configured scheduler token outside tests.
   - Missing token config returns `503`; invalid token returns `401`.

4. Deploy hardening:
   - `infra/gcp/deploy.sh` now:
     - fails early if `SCHEDULER_TOKEN` is empty
     - sets Cloud Run startup probe (`/health/ready`) and liveness probe (`/health/live`)
     - creates/updates Cloud Tasks queue before service deploy (to satisfy readiness checks)
     - always sets scheduler header `X-Scheduler-Token=...`

5. Tests added/updated:
   - Updated: `backend/app/tests/test_health.py`
   - New: `backend/app/tests/test_scheduler_security.py`
   - New: `backend/app/tests/test_settings_security.py`

### Validation Performed In This Chat
- Passed: `py -3.11 -m pytest backend/app/tests/test_health.py backend/app/tests/test_scheduler_security.py backend/app/tests/test_settings_security.py backend/app/tests/test_queue_orchestration.py backend/app/tests/test_pipeline_stale_lock.py backend/app/tests/test_jobs.py backend/app/tests/test_api_smoke.py` (`26 passed`)
- Passed: `py -3.11 -m compileall backend/app/api backend/app/utils backend/app/services backend/app/tests`
- Passed (staging):
  - `GET /health/live` -> `200`
  - `GET /health/ready` -> `200` with checks `database/cloud_tasks/gcs=ready`
  - `POST /api/v1/ml/drift-report` without token -> `503` (`Scheduler token is not configured`)
  - Cloud Run staging revision `sg-route-opt-api-staging-00013-b7h` now configured with:
    - startup probe: `GET /health/ready`
    - liveness probe: `GET /health/live`
