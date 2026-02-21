# Next Chat Context (SG-Route-OPT)

## Timestamp
- Generated: February 20, 2026
- Purpose: handoff after frontend status fixes + new OneMap->Vertex ETA data pipeline scaffolding

## Repo Snapshot
- Repo: `c:\Users\User\OneDrive\Documents\FYP Documents\SG-Route-OPT`
- Branch: `main`
- HEAD: `39a47a0`
- Remote: `https://github.com/jasonjlcl/SG-Route-OPT.git`

## Recently Pushed Commits
1. `39a47a0` - `fix(frontend): normalize optimize job result and tighten workflow completion states`
   - Fixes incorrect "Infeasible" render when optimize pipeline actually succeeded.
   - Tightens workflow step completion behavior.
2. `7b4ebbc` - `docs: add ML training guide runbook`
   - Added `docs/ML_TRAINING_GUIDE.md`.

## What Was Fixed In Frontend

### 1) Optimize run summary false infeasible bug
- Root cause: optimization page read top-level `job.result_ref` directly, but pipeline stores final optimize payload under `result_ref.optimize`.
- Effect: `feasible` was undefined and rendered as `Infeasible`.
- Fix:
  - Added normalize function for job result payload.
  - Read warnings from normalized payload too.
- File:
  - `frontend/src/pages/OptimizationPage.tsx`

### 2) Workflow ticks only on true completion
- Step status mapping made stricter:
  - `validate`: complete only when `VALID`
  - `geocode`: complete only when `COMPLETE`
  - `optimize`: complete only when `COMPLETE`
- Follow-up tweak requested by user:
  - `validation_state=PARTIAL` now shows `in_progress` (not `attention`).
- File:
  - `frontend/src/hooks/useWorkflowState.ts`

## New Uncommitted Work Added (Not Pushed Yet)

### OneMap -> Vertex ETA pipeline scaffold
Created new tooling under:
- `tools/onemap_vertex_eta/onemap_collect_train.py`
- `tools/onemap_vertex_eta/requirements.txt`
- `tools/onemap_vertex_eta/README.md`

Implemented CLI commands:
- `build-address-pool`
- `collect --target_rows 20000 --sleep_ms 200`
- `train`
- `collect-and-train`

Core behavior implemented:
- data.gov.sg poll-download fetch for 4 specified dataset IDs
- address point extraction from GeoJSON point geometry
- SG bounds filter + dedupe by `(dataset_id, lat6, lon6)`
- `addresses.csv` generation with `point_id, lat, lon, dataset_source`
- OD sampling with required distance mix (40/40/20 for 1-3km / 3-8km / 8-20km)
- OneMap routing labels with retries/backoff/rate sleep
- BigQuery insert into `eta_sg.onemap_eta_training` partitioned by `timestamp_iso`
- Vertex AutoML Tabular Regression train path (`target=actual_duration_s`)
- Open Data Licence attribution included in README + output metadata rows

Sanity checks run:
- `.venv\Scripts\python.exe -m py_compile tools/onemap_vertex_eta/onemap_collect_train.py` -> pass
- `.venv\Scripts\python.exe tools/onemap_vertex_eta/onemap_collect_train.py --help` -> pass

## Current Working Tree Notes
There are many unrelated local modifications in backend/frontend/sample_data/infra from prior work.
Do NOT mass-revert.
Isolate commits by concern.

Notable uncommitted new paths:
- `tools/` (new pipeline files)
- `backend/app/tests/test_routing_cache.py`
- `infra/gcp/cloudbuild.backend.yaml`
- multiple `sample_data/*.csv`

## Suggested Next Actions
1. Decide whether to commit/push the new `tools/onemap_vertex_eta/*` pipeline now.
2. If yes, do a dedicated commit for only those files.
3. Optionally run a dry command (no GCP writes) first:
   - `build-address-pool`
4. Then run full collect/train with env vars set:
   - `ONEMAP_EMAIL`, `ONEMAP_PASSWORD`, `GCP_PROJECT_ID`, optional `GCP_REGION`, `BQ_DATASET`.
5. Keep unrelated dirty files out of this commit.
