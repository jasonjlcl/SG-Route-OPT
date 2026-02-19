# ML Training Guide

This guide explains how to train and use ML ETA models in this project.

## 1) What models exist

There are two ETA model layers:

- Baseline ETA model
  - Trained from `ActualTravelTime` records.
  - Used by `/ml` page and `/api/v1/ml/*` endpoints.
  - Runtime label: usually `ml_baseline` (or `onemap`/`google_traffic` fallback depending on flow).
- Uplift model (optional)
  - Learns congestion factor vs static duration.
  - Uses Google-traffic-derived samples.
  - Runtime label: `ml_uplift` when enabled and artifact is available.

## 2) Prerequisites

Before training baseline ETA model, make sure:

1. Backend is running.
2. You have actual trip data (ground truth).
3. `ActualTravelTime` table has enough rows.

Useful env flags:

- `FEATURE_ML_UPLIFT=true|false`
- `FEATURE_VERTEX_AI=true|false`
- `FEATURE_GOOGLE_TRAFFIC=true|false`
- `ML_DRIFT_THRESHOLD` (default `0.2`)
- `ML_RETRAIN_MIN_ROWS` (default `200`)

## 3) Baseline model training (recommended path)

### Option A: Use Web UI (`/ml`)

1. Open `/ml`.
2. In **Upload actuals**, upload CSV with columns:
   - `origin_lat`
   - `origin_lon`
   - `dest_lat`
   - `dest_lon`
   - `timestamp_iso`
   - `actual_duration_s`
3. Click **Train from actuals**.
4. Wait for training job to complete.
5. In **Rollout**, set:
   - `Active version` = new model version
   - Optional canary settings
6. Click **Save rollout**.

### Option B: Train via API

Upload actuals:

```bash
curl -X POST "http://localhost:8000/api/v1/ml/actuals/upload" \
  -F "file=@./actuals.csv"
```

Start training job:

```bash
curl -X POST "http://localhost:8000/api/v1/ml/models/train" \
  -H "Content-Type: application/json" \
  -d "{}"
```

Set rollout:

```bash
curl -X POST "http://localhost:8000/api/v1/ml/config" \
  -H "Content-Type: application/json" \
  -d '{
    "active_model_version": "v20260218132542656055",
    "canary_model_version": null,
    "canary_percent": 0,
    "canary_enabled": false
  }'
```

## 4) Evaluate if model actually improves ETA

Run formal baseline vs model comparison:

```bash
curl "http://localhost:8000/api/v1/ml/evaluation/compare?days=30&limit=5000"
```

Generate evaluation report package:

```bash
curl -X POST "http://localhost:8000/api/v1/ml/evaluation/run" \
  -H "Content-Type: application/json" \
  -d '{"days":30,"limit":5000,"model_version":null}'
```

Track drift:

```bash
curl -X POST "http://localhost:8000/api/v1/ml/drift-report?trigger_retrain=false"
```

Important:

- If there are no recent actuals, evaluation returns 0 samples and you cannot conclude improvement.
- Prioritize MAE/MAPE and segment-level metrics (peak/off-peak) before promotion.

## 5) Confirm model is used in optimization

1. Run optimization from `/optimization`.
2. Open `/results`.
3. Check **ETA source** badge:
   - `google_traffic` -> live traffic used
   - `ml_uplift` -> uplift model applied
   - `ml_baseline` -> baseline ML model used
   - `onemap` -> fallback path

If you requested live traffic but see fallback warning, Google path was unavailable and system used baseline ETA path.

## 6) Uplift model training (optional, advanced)

This is separate from `/ml/models/train`.

Collect uplift samples:

```bash
python -m ml_uplift.collect_samples --dataset-id 1 --sample-elements 25
```

Train uplift model:

```bash
python -m ml_uplift.train --min-rows 120
```

Artifacts:

- Samples: `backend/data/ml_uplift/samples.csv`
- Model artifacts: `backend/app/ml_uplift/artifacts/`

Then enable with:

- `FEATURE_ML_UPLIFT=true`

## 7) Vertex AI notes

- Vertex support is optional and flag-driven (`FEATURE_VERTEX_AI`).
- `/api/v1/ml/models/train/vertex` forces registration attempt in Vertex after local training.
- If Vertex is not fully configured (`GCP_PROJECT_ID`, `GCS_BUCKET`, credentials), training still completes locally and logs Vertex error metadata.

## 8) Troubleshooting checklist

1. Training succeeds but no improvement:
   - Check actuals quality/coverage and sample size.
   - Compare by segments (peak/off-peak, route distance bands).
2. Evaluation shows 0 samples:
   - Upload actuals first.
   - Ensure timestamps are recent enough for selected `days` window.
3. ETA source shows `onemap` instead of ML:
   - Verify rollout is set and active version exists.
   - Check model artifact path exists.
4. Uplift not applied:
   - Ensure `FEATURE_ML_UPLIFT=true`.
   - Ensure uplift artifact exists (`latest_model.joblib`).

## 9) Recommended operating cycle

1. Upload new actuals daily/weekly.
2. Train model.
3. Run formal evaluation.
4. Canary rollout first.
5. Promote to active if KPI delta is stable.
6. Run drift report on schedule and retrain when threshold is crossed.
