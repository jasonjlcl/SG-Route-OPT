# Next Chat Context (SG-Route-OPT)

## Date + Purpose
- Context timestamp: February 17, 2026 (local)
- Purpose: handoff after committing Google traffic-aware reference integration, ML uplift pipeline, evaluation harness/UI, and docs updates.

## Repository Snapshot
- Repo path: `c:\Users\User\OneDrive\Documents\FYP Documents\SG-Route-OPT`
- Branch: `main` (tracking `origin/main`)
- Remote: `origin -> https://github.com/jasonjlcl/SG-Route-OPT.git`

### Latest Commits (Most Recent First)
- `fd41dde` — docs: update env setup and demo instructions for uplift/evaluation
- `510e4a9` — feat(frontend): add evaluation dashboard and ML uplift ETA indicators
- `04d9ce1` — feat(backend): add Google Routes provider, ML uplift pipeline, and evaluation jobs

## Current Working Tree
Modified files (intentionally left uncommitted):
- `NEXT_CHAT_CONTEXT.md` (this handoff update)
- `frontend/tsconfig.tsbuildinfo` (generated; do not commit)
- `frontend/vite.config.ts` (existing line-ending/worktree noise; avoid functional changes)

## Implemented in This Session

### 1) Backend: Google Routes Provider (Reference Traffic)
- Added provider module with strict field masks and structured fallback errors:
  - `backend/app/providers/google_routes.py`
- Supports:
  - `compute_routes(...)` with leg `duration` + `staticDuration` + `distanceMeters`
  - `compute_route_matrix(...)` with guardrails
  - token-bucket rate limiting, retry/backoff, TTL leg cache
- Added compatibility bridge for existing optimization code:
  - `backend/app/services/traffic_provider_google.py`

### 2) Backend: Feature Flags + Env Alignment
Added/updated settings for required flags and aliases:
- `FEATURE_GOOGLE_TRAFFIC`
- `GOOGLE_ROUTES_API_KEY` (preferred, server-side)
- `GOOGLE_MAPS_API_KEY` (legacy alias)
- `GOOGLE_ROUTING_PREFERENCE`
- `GOOGLE_MATRIX_MAX_ELEMENTS`
- `GOOGLE_CACHE_TTL_SECONDS`
- `GOOGLE_TIMEOUT_SECONDS`
- `GOOGLE_RATE_LIMIT_QPS`
- `FEATURE_ML_UPLIFT`
- `FEATURE_EVAL_DASHBOARD`

Files:
- `backend/app/utils/settings.py`
- `.sample.env`

### 3) Backend: ML Uplift Pipeline
Added new uplift package and scripts:
- `backend/app/ml_uplift/`:
  - `schema.py`, `features.py`, `storage.py`, `model.py`
  - `collect_samples.py`, `train.py`
- module wrappers for execution:
  - `python -m ml_uplift.collect_samples`
  - `python -m ml_uplift.train`
- entrypoint wrappers:
  - `backend/ml_uplift/collect_samples.py`
  - `backend/ml_uplift/train.py`
- data path scaffold:
  - `backend/data/ml_uplift/samples.csv`
- service integration:
  - `backend/app/services/ml_uplift.py`

### 4) Backend: Optimizer + ETA Integration
- Integrated uplift factor inference into matrix building behind `FEATURE_ML_UPLIFT`.
- Added bounded congestion factors and matrix strategy metadata.
- Post-optimization ETA refinement now uses Google route legs (`duration` and `staticDuration`) where available.
- Added sample logging from refined Google legs for uplift training rows.
- Maintains fallback behavior when Google is unavailable.

Main file:
- `backend/app/services/optimization.py`

### 5) Backend: Evaluation Harness + API
Added prediction-level and planning-level proof module:
- `backend/app/services/ml_uplift_evaluation.py`
  - prediction metrics (baseline static vs ML uplift against Google reference samples)
  - planning KPI simulation (late stops, on-time rate, overtime, makespan)
  - report ZIP generation (JSON + CSV)

Added API and job wiring:
- `backend/app/api/evaluation.py`
- `backend/app/services/job_tasks.py` (job type `ML_UPLIFT_EVAL`)
- `backend/app/main.py` and `backend/app/api/__init__.py` router wiring

### 6) Backend: Existing API/Schema/Model Wiring
Extended prior live-traffic and ETA-source wiring:
- `use_live_traffic` request plumbing in optimize/resequence paths
- plan metadata fields (`eta_source`, `traffic_timestamp_iso`, `live_traffic_requested`)
- schema propagation of ETA metadata and warnings
- health flags now include:
  - `feature_google_traffic`
  - `feature_ml_uplift`
  - `feature_eval_dashboard`

Files include:
- `backend/app/api/datasets.py`
- `backend/app/api/jobs.py`
- `backend/app/api/plans.py`
- `backend/app/models/entities.py`
- `backend/app/schemas/api.py`
- `backend/app/services/job_pipeline.py`
- `backend/app/utils/db.py`
- `backend/app/api/health.py`

### 7) Frontend: Evaluation Dashboard + ETA Labels
Added new route/page:
- `/evaluation`
- `frontend/src/pages/EvaluationPage.tsx`

Updated frontend API/types and nav:
- `frontend/src/api.ts`
- `frontend/src/types.ts`
- `frontend/src/App.tsx`
- `frontend/src/components/layout/TopBar.tsx`

Updated optimization/results UX labels:
- `frontend/src/pages/OptimizationPage.tsx`
- `frontend/src/pages/ResultsPage.tsx`

### 8) Tests Added/Updated
- `backend/app/tests/test_google_traffic.py`
- `backend/app/tests/test_ml_uplift_and_evaluation.py`
- `backend/app/tests/test_health.py`

## Validation Status

### Backend tests run
1. `\.\.venv-backend\Scripts\python.exe -m pytest backend/app/tests/test_google_traffic.py backend/app/tests/test_resequence.py backend/app/tests/test_jobs.py backend/app/tests/test_health.py backend/app/tests/test_ml_uplift_and_evaluation.py`
- Result: `11 passed`

2. `\.\.venv-backend\Scripts\python.exe -m pytest backend/app/tests/test_ml_evaluation_and_ab.py`
- Result: `2 passed`

### Frontend build
- `cd frontend && npm run build`
- Result: success (existing chunk-size warning remains non-blocking)

## Deployment/Runtime Env Vars (Key Set)
Set in Cloud Run service env/secrets:
- `FEATURE_GOOGLE_TRAFFIC`
- `GOOGLE_ROUTES_API_KEY` (preferred secret)
- `GOOGLE_ROUTING_PREFERENCE`
- `GOOGLE_MATRIX_MAX_ELEMENTS`
- `GOOGLE_CACHE_TTL_SECONDS`
- `GOOGLE_TIMEOUT_SECONDS`
- `GOOGLE_RATE_LIMIT_QPS`
- `FEATURE_ML_UPLIFT`
- `FEATURE_EVAL_DASHBOARD`

Legacy aliases still recognized:
- `GOOGLE_MAPS_API_KEY`
- `GOOGLE_TRAFFIC_MODE`
- `GOOGLE_MAX_ELEMENTS_PER_JOB`

## Suggested Next Chat Objectives
1. Push local commits to remote (if not already pushed) and verify GitHub branch state.
2. Deploy backend/frontend with new env vars enabled in Cloud Run.
3. Run interview demo flow:
   - optimize baseline vs uplift
   - show `/evaluation` KPI deltas + report ZIP
   - show ETA source badges in `/results`
4. Verify Google quota/auth behavior and fallback telemetry in production.
5. Configure custom domain + managed SSL (still pending from prior context).

## Quick Commands
- Run targeted backend tests:
  - `\.\.venv-backend\Scripts\python.exe -m pytest backend/app/tests/test_google_traffic.py backend/app/tests/test_resequence.py backend/app/tests/test_jobs.py backend/app/tests/test_health.py backend/app/tests/test_ml_uplift_and_evaluation.py`
- Run frontend build:
  - `cd frontend && npm run build`
- Backend dev server:
  - `cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- Frontend dev server:
  - `cd frontend && npm run dev`
- Show latest commits:
  - `git log --oneline -n 5`
