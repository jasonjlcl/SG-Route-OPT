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

---

## Update (February 22, 2026 - Phase 6 Started: Scale Guardrails)

### Completed In This Chat
1. Added optimize request guardrail settings:
   - `OPTIMIZE_MAX_STOPS` (default `120`)
   - `OPTIMIZE_MAX_MATRIX_ELEMENTS` (default `15000`)
   - Implemented in `backend/app/utils/settings.py` and documented in `.sample.env` + `README.md`.

2. Added request-boundary scale validation service:
   - New: `backend/app/services/scale_guardrails.py`
   - Validation computes:
     - dataset stop count
     - estimated directed matrix size (`(stops + depot)^2 - (stops + depot)`)
   - Fails fast with explicit 4xx AppErrors:
     - `OPTIMIZE_MAX_STOPS_EXCEEDED`
     - `OPTIMIZE_MAX_MATRIX_ELEMENTS_EXCEEDED`

3. Wired guardrails into optimize entrypoints:
   - `POST /api/v1/datasets/{dataset_id}/optimize`
   - `POST /api/v1/datasets/{dataset_id}/optimize/ab-test`
   - `POST /api/v1/jobs/optimize`

4. Added API tests for guardrail behavior:
   - New: `backend/app/tests/test_scale_guardrails.py`
   - Covers stop-limit rejection and matrix-limit rejection with actionable error details.

### Validation Performed In This Chat
- Passed: `py -3.11 -m pytest backend/app/tests/test_scale_guardrails.py` (`3 passed`)
- Passed: `py -3.11 -m pytest -vv backend/app/tests/test_jobs.py` (`3 passed`)
- Passed: `py -3.11 -m compileall backend/app/api/datasets.py backend/app/api/jobs.py backend/app/services/scale_guardrails.py backend/app/utils/settings.py backend/app/tests/test_scale_guardrails.py`

---

## Update (February 22, 2026 - Phase 6 Continued: Threshold Tuning + Frontend UX)

### Completed In This Chat
1. Tuned guardrail defaults for production single-instance traffic profile:
   - Updated defaults:
     - `OPTIMIZE_MAX_STOPS=80`
     - `OPTIMIZE_MAX_MATRIX_ELEMENTS=6500`
   - Applied in:
     - `backend/app/utils/settings.py`
     - `.sample.env`
     - `README.md`

2. Ensured deploy-time production defaults are explicit:
   - Added `OPTIMIZE_MAX_STOPS` and `OPTIMIZE_MAX_MATRIX_ELEMENTS` env wiring in `infra/gcp/deploy.sh`.
   - Defaults in deploy script now align with tuned production profile.

3. Added actionable frontend UX for scale-guardrail errors:
   - Updated `frontend/src/pages/OptimizationPage.tsx` with structured error mapping for:
     - `OPTIMIZE_MAX_STOPS_EXCEEDED`
     - `OPTIMIZE_MAX_MATRIX_ELEMENTS_EXCEEDED`
   - UI now shows clear cause + next-step guidance and a direct `Go to Upload` action for request-size issues.
   - Added matching toast messages with concrete limit context.

### Validation Performed In This Chat
- Passed: `py -3.11 -m pytest backend/app/tests/test_scale_guardrails.py backend/app/tests/test_settings_security.py` (`6 passed`)
- Passed: `npm run build` (frontend TypeScript + Vite production build)

---

## Update (February 22, 2026 - Phase 7 Started: Observability + Alerts)

### Completed In This Chat
1. Added backend observability log markers for alertable signals:
   - `DB_LOCK_RETRY` logging added in:
     - `backend/app/services/jobs.py`
     - `backend/app/utils/db.py`
   - `PIPELINE_STALE_LOCK_RECLAIMED` logging added in:
     - `backend/app/services/jobs.py` (`lock_step` stale reclaim branch)
   - Optimize completion/latency markers added in:
     - `backend/app/services/job_pipeline.py`
     - emits:
       - `OPTIMIZE_PIPELINE_COMPLETE`
       - `OPTIMIZE_LATENCY_SLOW` (when threshold exceeded)

2. Added optimize latency warning threshold setting:
   - `OPTIMIZE_LATENCY_WARN_SECONDS` (default `1200`)
   - Implemented in:
     - `backend/app/utils/settings.py`
     - `.sample.env`
     - `README.md`
   - Added test coverage for minimum bound validation in:
     - `backend/app/tests/test_settings_security.py`

3. Added deployable Phase 7 monitoring assets:
   - New apply script:
     - `infra/gcp/monitoring/apply_phase7_monitoring.sh`
   - New alert policy templates:
     - `infra/gcp/monitoring/phase7/alert_policies/cloud_tasks_queue_depth_high.json`
     - `infra/gcp/monitoring/phase7/alert_policies/cloud_tasks_retry_delay_high.json`
     - `infra/gcp/monitoring/phase7/alert_policies/cloud_tasks_failure_rate_high.json`
     - `infra/gcp/monitoring/phase7/alert_policies/db_lock_retry_spike.json`
     - `infra/gcp/monitoring/phase7/alert_policies/fallback_event_rate_spike.json`
     - `infra/gcp/monitoring/phase7/alert_policies/signed_url_failures_detected.json`
     - `infra/gcp/monitoring/phase7/alert_policies/optimize_latency_slow_detected.json`
     - `infra/gcp/monitoring/phase7/alert_policies/stale_lock_reclaimed_detected.json`
   - New dashboard template:
     - `infra/gcp/monitoring/phase7/dashboard/sg_route_opt_core_slo_dashboard.json`
   - Added Phase 7 monitoring runbook:
     - `infra/gcp/monitoring/phase7/README.md`

4. Deploy integration added (opt-in):
   - `infra/gcp/deploy.sh` now supports:
     - `RUN_PHASE7_MONITORING=true|false` (default `false`)
     - `MONITORING_NOTIFICATION_CHANNELS` (optional)
   - When enabled, deploy runs `infra/gcp/monitoring/apply_phase7_monitoring.sh`.

5. Documentation updated:
   - `README.md` now documents Phase 7 monitoring script/assets and covered signals.

### Validation Performed In This Chat
- Passed: `py -3.11 -m pytest backend/app/tests/test_settings_security.py backend/app/tests/test_scale_guardrails.py backend/app/tests/test_pipeline_stale_lock.py` (`12 passed`)
- Passed: `py -3.11 -m compileall backend/app/services/jobs.py backend/app/services/job_pipeline.py backend/app/utils/db.py backend/app/utils/settings.py`
- Passed: JSON validation of all `infra/gcp/monitoring/phase7/**/*.json` files via `python -m json.tool`
- Note: local shell syntax check with `bash -n` could not be run in this Windows environment because WSL bash runtime is unavailable.

### Remaining To Close Phase 7
1. Run `infra/gcp/monitoring/apply_phase7_monitoring.sh` in staging project and verify policy/dashboard creation.
2. Execute staging drill scenarios from `infra/gcp/monitoring/phase7/README.md` to confirm incidents fire:
   - slow optimize
   - stale lock reclaim
   - fallback spikes
   - signed URL failure path
   - Cloud Tasks retry/failure signals
3. Tune thresholds using staging baseline data before production enablement.

---

## Update (February 22, 2026 - Phase 7 Staging Execution Attempt + Current State)

### Completed In This Chat
1. Verified staging GCP targets:
   - Project: `gen-lang-client-0328386378`
   - Staging service: `sg-route-opt-api-staging`
   - Staging queue: `routeapp-queue-stg`

2. Applied Phase 7 monitoring assets in staging (PowerShell equivalent of apply script due Windows bash/gcloud path issues):
   - Logs-based metrics confirmed:
     - `sg_route_opt_db_lock_retry_count`
     - `sg_route_opt_fallback_event_count`
     - `sg_route_opt_signed_url_failure_count`
     - `sg_route_opt_optimize_slow_count`
     - `sg_route_opt_stale_lock_reclaimed_count`
     - `sg_route_opt_optimize_complete_count`
   - Alert policies created (Phase 7 set, 8 policies total).
   - Dashboard created:
     - `sg-route-opt - Core SLO dashboard`
     - resource: `projects/858316205970/dashboards/05146150-d3f1-471a-bc88-a6cbfc13dcde`

3. Started slow-latency drill setup:
   - Updated staging service env:
     - `OPTIMIZE_LATENCY_WARN_SECONDS=1`
   - Ran a full staging optimize job to completion (`SUCCEEDED`) as signal probe.

### Important Findings
1. No `OPTIMIZE_LATENCY_SLOW` logs were emitted in staging after the probe job.
2. Root cause:
   - staging revision is still on older backend image that does not include new Phase 7 log markers yet.
3. Attempted to build + deploy current backend image to staging:
   - first build failed due image-tag formatting issue (fixed locally).
   - second build/deploy command was started but user interrupted before completion.

### Additional Note
- `pip` was checked/upgraded on local machine for Python 3.11:
  - current: `pip 26.0.1` (already up to date).

### Remaining Steps (Next Chat Priority)
1. Finish staging backend deploy with current Phase 7 code:
   - build image from current workspace
   - update `sg-route-opt-api-staging` to that image
   - confirm latest revision serves 100% traffic

2. Re-run Phase 7 staging drills (post-deploy):
   - slow optimize latency (`OPTIMIZE_LATENCY_SLOW`)
   - stale lock reclaim (`PIPELINE_STALE_LOCK_RECLAIMED`)
   - fallback spike signals
   - signed URL failure signal
   - Cloud Tasks retry/failure signal

3. Verify incident creation and dashboard signal visibility:
   - ensure each corresponding alert policy opens incident during drill
   - capture policy IDs/incidents + timestamps in notes

4. Tune thresholds based on staging baseline and revert temporary drill env vars:
   - restore `OPTIMIZE_LATENCY_WARN_SECONDS` from drill value back to production candidate
   - clear any retry-drill env vars after validation.

---

## Update (February 22, 2026 - Phase 7 Staging Deploy + Drill Validation: Slow Latency and Stale Lock)

### Completed In This Chat
1. Local validation re-run before staging changes:
   - Passed: `py -3.11 -m pytest backend/app/tests/test_settings_security.py backend/app/tests/test_scale_guardrails.py backend/app/tests/test_pipeline_stale_lock.py` (`12 passed`)
   - Passed: `py -3.11 -m compileall ...` on touched backend files.
   - Passed: `npm run build` (frontend).

2. Finished staging backend deploy with current Phase 7 image:
   - Built image from current workspace:
     - `gcr.io/gen-lang-client-0328386378/sg-route-opt-api-staging:phase7-20260222000000`
     - digest: `sha256:7767b3d3a29db2bda1c70c4d99748ece8af1f9d3d93f7414aebe0c490dc8ddc8`
   - Deployed to staging service:
     - revision `sg-route-opt-api-staging-00016-xtk` (100% traffic)
   - Key finding on failed prior revision:
     - `sg-route-opt-api-staging-00015-xxf` failed startup because `OPTIMIZE_LATENCY_WARN_SECONDS=1` violated new settings minimum (`>=60`).

3. Executed Phase 7 drill for stale lock reclaim + slow optimize latency:
   - Temporary drill env vars set:
     - `OPTIMIZE_LATENCY_WARN_SECONDS=60`
     - `PIPELINE_RETRY_DRILL_STEP=BUILD_MATRIX`
     - `PIPELINE_RETRY_DRILL_DELAY_SECONDS=90`
     - `PIPELINE_STEP_LEASE_SECONDS=60`
   - Note:
     - first attempt to set these vars created bad revision `sg-route-opt-api-staging-00017-qcz` due PowerShell comma parsing; corrected with quoted `--update-env-vars`.
     - corrected drill revision: `sg-route-opt-api-staging-00018-bcx`.
   - Drill workload:
     - uploaded dataset (`dataset_id=1`)
     - optimize job: `job_b2b5467937bf42319819c1d0cc7879ca`
     - final status: `SUCCEEDED`
     - job timestamps:
       - created: `2026-02-22T04:03:58.768991Z`
       - completed: `2026-02-22T04:08:19.014008Z`
     - evidence in job payload:
       - `steps.BUILD_MATRIX.retry_drill_injected=true`
       - `steps.BUILD_MATRIX.stale_reclaimed=1`

4. Verified Phase 7 signal logs in staging:
   - `PIPELINE_STALE_LOCK_RECLAIMED`:
     - `2026-02-22T04:05:32.363114Z`
     - revision `sg-route-opt-api-staging-00018-bcx`
     - includes `job_id=job_b2b5467937bf42319819c1d0cc7879ca`
   - `OPTIMIZE_LATENCY_SLOW`:
     - `2026-02-22T04:08:19.015408Z`
     - revision `sg-route-opt-api-staging-00018-bcx`
     - includes `latency_s=260 threshold_s=60`

5. Verified alert incidents opened for both drilled policies:
   - stale lock policy:
     - policy: `projects/gen-lang-client-0328386378/alertPolicies/4652221071533853734`
     - alert: `projects/gen-lang-client-0328386378/alerts/0.o4ke6ivth928`
     - open time: `2026-02-22T04:09:02Z`
   - optimize latency policy:
     - policy: `projects/gen-lang-client-0328386378/alertPolicies/10906907387417997955`
     - alert: `projects/gen-lang-client-0328386378/alerts/0.o4ke8yoozov0`
     - open time: `2026-02-22T04:12:00Z`

6. Reverted temporary drill settings after validation:
   - removed:
     - `PIPELINE_RETRY_DRILL_STEP`
     - `PIPELINE_RETRY_DRILL_DELAY_SECONDS`
     - `PIPELINE_STEP_LEASE_SECONDS`
   - restored:
     - `OPTIMIZE_LATENCY_WARN_SECONDS=1200`
   - cleanup deploy revision:
     - `sg-route-opt-api-staging-00019-6rr` (100% traffic)
   - readiness check:
     - `GET /health/ready` returned `ready=true` with `database/cloud_tasks/gcs=ready`.

## NEXT CHAT START HERE (February 22, 2026)

### Current Production State
- API service: `sg-route-opt-api`
- Latest revision: `sg-route-opt-api-00047-97v`
- Active image: `gcr.io/gen-lang-client-0328386378/sg-route-opt-api:prod-mlfix-20260222171834`
- Health:
  - `GET https://api.sgroute.com/health/ready` -> `ready=true`
  - `GET https://api.sgroute.com/api/v1/health` -> `status=ok`, `env=prod`
- ML config:
  - active model: `v20260222075015196509`
  - `feature_vertex_ai=true`

### What Was Fixed
- ML fallback issue fixed for optimize flow:
  - optimize now returns `eta_source=ml_baseline` (no longer `onemap`/`fallback_v1` by default).
- Backend hardening shipped:
  - Vertex batch job now has machine/replica settings and timeout guardrails.
  - model loading can fallback from GCS artifact (`artifact_gcs_uri`) if local file missing.
- GCS IAM added for Vertex service agents on `gs://route_app`.

### Still Open
- Async optimize currently succeeds with ML baseline, but Vertex batch override still times out in production:
  - `vertex_batch_used=false`
  - `vertex_reason=batch_prediction_unavailable`
  - recent log: `Vertex batch prediction timed out ... timeout_s=120`

### Suggested Immediate Next Steps
1. Decide whether to keep Vertex batch override enabled.
2. If yes, tune:
   - `VERTEX_BATCH_TIMEOUT_SECONDS` (increase from `120`)
   - machine/replica sizing (`VERTEX_BATCH_MACHINE_TYPE`, replica counts)
   - check Vertex quotas in `asia-southeast1`.
3. Re-run async optimize smoke and capture:
   - `eta_source`
   - `model_version`
   - `vertex_batch_used`
   - `vertex_reason`
4. If Vertex remains slow/unreliable, add an explicit feature flag to disable batch override and keep local `ml_baseline` path as default.

---

### Remaining To Close Phase 7
1. Run remaining staging drills and capture incident evidence:
   - fallback spike signal
   - signed URL failure signal
   - Cloud Tasks retry/failure signals
2. Tune thresholds with staging baseline data and decide whether to keep current policy thresholds or adjust before production enablement.
3. Close or acknowledge currently open drill incidents after evidence capture.

---

## Update (February 22, 2026 - Phase 7 Remaining Drills Completed: Fallback, Signed URL, Cloud Tasks)

### Completed In This Chat
1. Confirmed Namecheap deploy URL and used it for deployment URL validation:
   - Domain mappings:
     - `api.sgroute.com` -> `sg-route-opt-api` (Ready)
     - `app.sgroute.com` -> `sg-route-opt-web` (Ready)
   - Validation call using Namecheap URL:
     - `GET https://api.sgroute.com/api/v1/health` -> `200`
     - response included `env=prod` and feature flags.
   - Note:
     - failure-injection drills were kept on staging service `sg-route-opt-api-staging` for safety.

2. Fallback spike drill completed (`sg-route-opt-api-staging`):
   - Temporary staging override:
     - `ONEMAP_ROUTING_URL=https://invalid.onemap.invalid/route`
   - Revision:
     - `sg-route-opt-api-staging-00020-sn5`
   - Workload:
     - async batch: 50 optimize jobs queued (`dataset_id=1`)
     - then controlled sustained run with queue paused:
       - 8 sync optimize calls over ~12.6 minutes (`sync=true`) with varying `workday_start`.
   - Log evidence:
     - repeated `OneMap route fallback to heuristic estimate: [Errno -2] Name or service not known`.
   - Incident evidence:
     - alert: `projects/gen-lang-client-0328386378/alerts/0.o4kf8j7r3arf`
     - policy: `projects/gen-lang-client-0328386378/alertPolicies/8819614958033764935`
     - opened: `2026-02-22T04:55:16Z`
     - closed: `2026-02-22T05:01:32Z`

3. Signed URL failure drill completed (`sg-route-opt-api-staging`):
   - Created temporary drill service account:
     - `route-app-api-stg-drill-sa@gen-lang-client-0328386378.iam.gserviceaccount.com`
   - Granted required runtime roles except signBlob capability; switched staging service account to drill SA.
   - Revision:
     - `sg-route-opt-api-staging-00021-qzq`
   - Drill job:
     - `job_3e8c422da7bc4789ba752f3a6570f1df` (`SUCCEEDED`)
     - job result had export `signed_url=null` for maps and driver pack.
   - Log evidence:
     - `Failed to generate signed URL with IAM signing fallback`
     - includes `Permission 'iam.serviceAccounts.signBlob' denied`.
   - Incident evidence:
     - alert: `projects/gen-lang-client-0328386378/alerts/0.o4kfhnqecfp8`
     - policy: `projects/gen-lang-client-0328386378/alertPolicies/2316978444650425485`
     - opened: `2026-02-22T05:06:22Z`
     - closed: `2026-02-22T05:12:07Z`

4. Cloud Tasks retry/failure/depth drill completed (`sg-route-opt-api-staging`):
   - Restored staging to normal API SA and removed fallback URL override.
   - Enabled retry-injection drill:
     - `PIPELINE_RETRY_DRILL_STEP=GEOCODE`
     - `PIPELINE_RETRY_DRILL_DELAY_SECONDS=1`
   - Revision:
     - `sg-route-opt-api-staging-00022-56p`
   - Workload:
     - queued 330 optimize jobs (`dataset_id=1`)
     - first/last IDs:
       - first: `job_61eb5724854c4f06ad4f841482a3c9c9`
       - last: `job_f0ef4ca5ee184c048e63aac7d6f798fc`
   - Incident evidence:
     - failure attempt rate:
       - alert: `projects/gen-lang-client-0328386378/alerts/0.o4kfrtqmqm82`
       - policy: `projects/gen-lang-client-0328386378/alertPolicies/2316978444650425863`
       - opened: `2026-02-22T05:18:44Z`
       - state: `OPEN` (at capture time)
     - queue depth:
       - alert: `projects/gen-lang-client-0328386378/alerts/0.o4kfvzozascl`
       - policy: `projects/gen-lang-client-0328386378/alertPolicies/6069703792096240434`
       - opened: `2026-02-22T05:23:48Z`
       - state: `OPEN` (at capture time)
     - retry delay p95:
       - alert: `projects/gen-lang-client-0328386378/alerts/0.o4kfxhgkma4c`
       - policy: `projects/gen-lang-client-0328386378/alertPolicies/1535196936256432291`
       - opened: `2026-02-22T05:25:37Z`
       - state: `OPEN` (at capture time)

5. Drill cleanup and restore completed:
   - Purged staging queue after evidence capture.
   - Removed retry drill env vars.
   - Deployed cleanup revision:
     - `sg-route-opt-api-staging-00023-dk9` (100% traffic)
   - Restored staging runtime identity:
     - `route-app-api-sa@gen-lang-client-0328386378.iam.gserviceaccount.com`
   - Deleted temporary drill SA:
     - `route-app-api-stg-drill-sa@gen-lang-client-0328386378.iam.gserviceaccount.com`
   - Readiness check:
     - `GET /health/ready` -> `ready=true` with `database/cloud_tasks/gcs=ready`.

### Remaining To Close Phase 7
1. Optionally wait for current Cloud Tasks drill incidents to auto-close after queue metrics settle, then capture final close timestamps.
2. Optionally tune Cloud Tasks policy thresholds using the collected drill baselines before production-level enablement.

---

## Update (February 22, 2026 - Phase 7 Steps 1-3 Closed: Re-apply, Drill Verification, Threshold Tuning)

### Completed In This Chat
1. Re-applied Phase 7 monitoring assets in staging project (Step 1):
   - Environment:
     - project: `gen-lang-client-0328386378`
     - service: `sg-route-opt-api-staging`
     - queue: `routeapp-queue-stg`
   - Note:
     - `bash`/WSL runtime is unavailable in this Windows host, so script logic was executed via PowerShell-equivalent `gcloud` upserts (same metrics/policies/dashboard behavior).
   - Verified:
     - logs-based metrics updated:
       - `sg_route_opt_db_lock_retry_count`
       - `sg_route_opt_fallback_event_count`
       - `sg_route_opt_signed_url_failure_count`
       - `sg_route_opt_optimize_slow_count`
       - `sg_route_opt_stale_lock_reclaimed_count`
       - `sg_route_opt_optimize_complete_count`
     - 8 Phase 7 alert policies enabled for staging labels.
     - dashboard replaced and active:
       - `projects/858316205970/dashboards/3d4a4fb1-ba76-4213-b6e4-412073a90581`

2. Confirmed staging drill scenarios fired incidents for all required signals (Step 2):
   - slow optimize:
     - `projects/gen-lang-client-0328386378/alerts/0.o4ke8yoozov0` (`CLOSED`)
   - stale lock reclaim:
     - `projects/gen-lang-client-0328386378/alerts/0.o4kg70ry7tok` (`CLOSED`)
   - fallback spikes:
     - `projects/gen-lang-client-0328386378/alerts/0.o4kf8j7r3arf` (`CLOSED`)
   - signed URL failure:
     - `projects/gen-lang-client-0328386378/alerts/0.o4kfhnqecfp8` (`CLOSED`)
   - Cloud Tasks retry/failure/depth:
     - retry delay: `projects/gen-lang-client-0328386378/alerts/0.o4kfxhgkma4c` (`CLOSED`)
     - failure rate: `projects/gen-lang-client-0328386378/alerts/0.o4kfrtqmqm82` (`CLOSED`)
     - queue depth: `projects/gen-lang-client-0328386378/alerts/0.o4kfvzozascl` (`CLOSED`)

3. Tuned thresholds using staging drill baseline and applied to staging policies (Step 3):
   - Updated templates:
     - `infra/gcp/monitoring/phase7/alert_policies/cloud_tasks_queue_depth_high.json`
       - queue depth threshold: `40 -> 80` for `10m`
     - `infra/gcp/monitoring/phase7/alert_policies/cloud_tasks_retry_delay_high.json`
       - retry delay p95 threshold: `120000ms -> 300000ms` for `10m`
     - `infra/gcp/monitoring/phase7/alert_policies/cloud_tasks_failure_rate_high.json`
       - non-OK attempt rate: `0.02/s for 5m -> 0.05/s for 10m`
     - `infra/gcp/monitoring/phase7/alert_policies/fallback_event_rate_spike.json`
       - fallback event rate: `0.03/s -> 0.05/s` for `10m`
     - `infra/gcp/monitoring/phase7/alert_policies/stale_lock_reclaimed_detected.json`
       - stale lock count trigger: `>0 -> >1` in `10m`
     - `infra/gcp/monitoring/phase7/alert_policies/optimize_latency_slow_detected.json`
       - slow optimize count trigger: `>0 -> >1` in `10m`
   - Updated runbook:
     - `infra/gcp/monitoring/phase7/README.md` with tuned-threshold section.
   - Verified live staging policies reflect tuned values via `gcloud monitoring policies describe`.

### Current Phase 7 Status
- Step 1 complete.
- Step 2 complete.
- Step 3 complete.

---

## Update (February 22, 2026 - Latest Handoff Snapshot After Push)

### Repo + Git State
- Repo: `c:\Users\User\OneDrive\Documents\FYP Documents\SG-Route-OPT`
- Branch: `main`
- Remote: `https://github.com/jasonjlcl/SG-Route-OPT.git`
- Latest pushed commit: `2ff5259`
- Commit message: `feat: add scale guardrails and phase7 monitoring operations`
- Local status at handoff: clean (`main` synced with `origin/main`)

### What Is Fully Completed
1. Phase 6 + Phase 7 code and ops changes are implemented and pushed:
   - scale guardrails backend + frontend UX
   - observability markers
   - Phase 7 monitoring assets (apply script, policies, dashboard, runbook)
   - deploy script support for monitoring apply
2. Phase 7 staging execution is completed end-to-end:
   - monitoring assets applied in staging
   - all required drills executed:
     - slow optimize
     - stale lock reclaim
     - fallback spikes
     - signed URL failure
     - Cloud Tasks retry/failure/depth
   - incidents confirmed for each signal
3. Threshold tuning (based on staging drill baseline) is completed and applied:
   - queue depth: `>80 for 10m`
   - retry delay p95: `>300000ms for 10m`
   - failure attempt rate: `>0.05/s for 10m`
   - fallback event rate: `>0.05/s for 10m`
   - stale lock reclaimed: `>1 in 10m`
   - slow optimize count: `>1 in 10m`

### Current Runtime/Monitoring State (at handoff)
- Staging service: `sg-route-opt-api-staging`
- Staging queue: `routeapp-queue-stg`
- Phase 7 dashboard active:
  - `projects/858316205970/dashboards/3d4a4fb1-ba76-4213-b6e4-412073a90581`
- Latest incident snapshot used for closure showed all required drill policies with recent alerts and closure timestamps captured in this file.

### Namecheap/Domain Note
- Custom domains mapped and routable:
  - `https://app.sgroute.com`
  - `https://api.sgroute.com`
- Production health checked via custom API domain:
  - `GET https://api.sgroute.com/api/v1/health` returned `200`

### Suggested Next Actions (if continuing)
1. Monitor staging for 24-48h with tuned thresholds and adjust only if new false positives appear.
2. Promote tuned Phase 7 policy thresholds to production policy set (if not already intended as shared defaults).
3. If needed, split `NEXT_CHAT_CONTEXT.md` into:
   - concise active handoff section at top
   - historical archive section/file for older updates.

---

## Update (February 22, 2026 - Production Persistence + Vertex Rollout Fixed End-to-End)

### Completed In This Chat
1. Production persistence root cause fixed (moved backend off ephemeral/local DB behavior):
   - Enabled required GCP APIs:
     - `sqladmin.googleapis.com`
     - `sql-component.googleapis.com`
   - Created Cloud SQL Postgres instance:
     - instance: `sg-route-opt-pg`
     - region: `asia-southeast1`
   - Provisioned database credentials:
     - database: `routeapp`
     - user: `routeapp`
   - Granted Cloud SQL access to backend runtime SA:
     - `roles/cloudsql.client` on
       `route-app-api-sa@gen-lang-client-0328386378.iam.gserviceaccount.com`
   - Wired Secret Manager-backed database URL:
     - secret: `DATABASE_URL` (latest version: `3`)
     - corrected DSN formatting/socket path issues that initially blocked startup.

2. Latest backend deployed with persistent DB wiring:
   - image: `gcr.io/gen-lang-client-0328386378/sg-route-opt-api:prod-fix-20260222153307`
   - live revision at validation:
     - `sg-route-opt-api-00042-s4v` (100% traffic)
   - service config now includes:
     - Cloud SQL connection annotation:
       `gen-lang-client-0328386378:asia-southeast1:sg-route-opt-pg`
     - `DATABASE_URL` from Secret Manager.

3. Database migrations executed successfully in production:
   - migration job: `sg-route-opt-api-db-migrate`
   - successful run:
     - `sg-route-opt-api-db-migrate-ckww2`
   - migration failures observed earlier were resolved by fixing args/env and DB URL.

4. Vertex model retrained and rollout re-applied:
   - actuals upload completed (`2600` rows).
   - training job succeeded:
     - `job_c5f7cd05ab91431da3e0170fb7f7ca79`
   - resulting model version:
     - `v20260222075015196509`
   - vertex model resource:
     - `projects/858316205970/locations/asia-southeast1/models/3553353300134854656`
   - active rollout updated to:
     - `v20260222075015196509`.

5. Persistence across restart verified:
   - forced new production revision rollout after model activation.
   - confirmed model state remained present after restart:
     - `GET /api/v1/ml/config` returns active model version set.
     - `GET /api/v1/ml/models` returns deployed model list including active version.

6. Production health/readiness checks passed post-fix:
   - `GET /health/ready` -> `ready=true` with `database/cloud_tasks/gcs=ready`.
   - `GET /api/v1/health` -> `status=ok`, `env=prod`, expected feature flags enabled.

### Current State Summary (Latest)
- Phase 7 staging monitoring/drills/tuning: complete.
- Production backend persistence: fixed via Cloud SQL + Secret Manager `DATABASE_URL`.
- Production migrations: completed.
- Vertex retrain + rollout: completed.
- Restart persistence verification: completed.

### Pending Steps (Next Chat)
1. Confirm Cloud SQL backup/maintenance settings (and private IP/VPC hardening if required by policy).
2. Run one live production optimize smoke test and verify expected ML response path (`eta_source`, model usage) on real request output.
3. Decide whether to retain temporary rollout/debug env markers (for example secret refresh or persistence-check timestamps) or clean them up.
4. Optionally prune older `DATABASE_URL` secret versions if your secret-retention policy requires it.
5. Update ops runbook with:
   - production Cloud SQL instance + migration job procedure
   - current active model version and verification commands.

---

## Update (February 22, 2026 - Production Hardening + Smoke Verification Pass)

### Completed In This Chat
1. Confirmed and hardened Cloud SQL production baseline:
   - instance: `sg-route-opt-pg`
   - backups enabled (`startTime=22:00`, retained backups `7`)
   - maintenance window set (Sunday `03:00` UTC)
   - deletion protection enabled
   - connector enforcement set to `REQUIRED`
   - effective org policy checks:
     - `constraints/sql.restrictPublicIp` -> `False`
     - `constraints/sql.restrictAuthorizedNetworks` -> `False`
   - note:
     - private IP is not enforced by current effective org policy; instance still has public IP enabled.

2. Ran live production optimize smoke tests (real API traffic):
   - uploaded and geocoded production datasets.
   - successful optimize sample:
     - `dataset_id=4`, `plan_id=4`, `status=SUCCESS`
     - response `eta_source=onemap` (`use_live_traffic=false`)
   - pipeline sample with jobs API:
     - `job_71627af1e6ce4693a8e25fd15b95044c` -> `SUCCEEDED`
     - `result_ref.optimize.model_version=fallback_v1`
     - `result_ref.vertex.vertex_batch_used=false`
     - `result_ref.vertex.reason=batch_prediction_unavailable`

3. Decided cleanup for temporary rollout/debug env markers:
   - removed from Cloud Run service `sg-route-opt-api`:
     - `DATABASE_URL_SECRET_REFRESH_TS`
     - `PERSISTENCE_CHECK_TS`
   - latest revision after cleanup:
     - `sg-route-opt-api-00044-k8w` (100% traffic)

4. Optional secret pruning executed:
   - `DATABASE_URL` versions `1` and `2` disabled.
   - `DATABASE_URL` version `3` remains enabled and in use.

5. Updated runbook docs:
   - `README.md` now includes:
     - production DB hardening state
     - migration job execution/verification procedure
     - active model version checks and smoke-test verification commands.

### Current Health
- `GET https://api.sgroute.com/health/ready` -> `ready=true`
- `GET https://api.sgroute.com/api/v1/health` -> `status=ok`, `env=prod`
- `GET https://api.sgroute.com/api/v1/ml/config` -> active model `v20260222075015196509`

### Remaining Risk / Follow-up
1. ML inference path is still not being used during optimize smoke runs:
   - observed `eta_source=onemap` and `model_version=fallback_v1`.
   - async pipeline indicates Vertex path not applied (`batch_prediction_unavailable`).
2. Investigate Vertex batch prediction integration/runtime behavior in `backend/app/services/vertex_ai.py` and `backend/app/services/job_pipeline.py` to restore `ml_baseline` / `ml_uplift` path in production optimize flows.

---

## Update (February 22, 2026 - ML Fallback Fixed, Vertex Batch Guardrailed, Production Re-deployed)

### Completed In This Chat
1. Root-cause fixes implemented in backend code:
   - `backend/app/services/vertex_ai.py`
     - added required Vertex batch machine configuration (`machine_type`, replica counts).
     - switched batch-job control to Vertex JobService API for stable job-name retrieval.
     - added bounded polling timeout to prevent `BUILD_MATRIX` stalls.
     - improved output parsing resiliency and warning logs.
   - `backend/app/services/ml_engine.py`
     - added robust model loading fallback from GCS (`artifact_gcs_uri`) when local artifact file is missing.
   - `backend/app/utils/settings.py`
     - added Vertex batch tuning settings:
       - `VERTEX_BATCH_MACHINE_TYPE`
       - `VERTEX_BATCH_STARTING_REPLICA_COUNT`
       - `VERTEX_BATCH_MAX_REPLICA_COUNT`
       - `VERTEX_BATCH_TIMEOUT_SECONDS`
       - `VERTEX_BATCH_POLL_INTERVAL_SECONDS`
     - added replica-count validation.

2. Config/docs updated:
   - `.sample.env` includes new Vertex batch env vars.
   - `README.md` env documentation updated with Vertex batch settings.

3. Production IAM hardening for Vertex/GCS path:
   - granted `roles/storage.objectAdmin` on `gs://route_app` to:
     - `service-858316205970@gcp-sa-aiplatform.iam.gserviceaccount.com`
     - `service-858316205970@gcp-sa-aiplatform-cc.iam.gserviceaccount.com`

4. Production deploys performed (latest active):
   - Cloud Run service `sg-route-opt-api` revision:
     - `sg-route-opt-api-00047-97v`
   - active image:
     - `gcr.io/gen-lang-client-0328386378/sg-route-opt-api:prod-mlfix-20260222171834`
   - migration job image updated to same tag:
     - `sg-route-opt-api-db-migrate`

5. Verification results (production):
   - readiness:
     - `GET /health/ready` -> `ready=true`
   - sync optimize smoke:
     - `eta_source=ml_baseline` (no longer `onemap`)
   - async optimize smoke (`job_7a3431b0a7f14d9fb870a86d0628bf82`):
     - `status=SUCCEEDED`
     - `eta_source=ml_baseline`
     - `model_version=v20260222075015196509`
     - `vertex_batch_used=false`
     - `vertex_reason=batch_prediction_unavailable`

### Current Status
- Critical issue fixed: production optimize no longer drops to `fallback_v1`/`onemap` by default; ML baseline path is active again.
- Vertex batch override is still not completing within timeout in production; code now fails fast and preserves local ML baseline path instead of hanging pipeline.

### Remaining Follow-up (Optional)
1. Tune Vertex batch capacity/timeout if you want `vertex_batch_used=true` in async matrix build:
   - increase `VERTEX_BATCH_TIMEOUT_SECONDS`
   - evaluate machine/replica sizing and project quotas.
2. Decide whether to keep Vertex batch enabled in async optimize or gate it behind an explicit feature flag.
