# Chapter 6 Local Evaluation Summary

Date: 2026-03-15

## Setup

- Source DB inspected: `backend/app.db`
- Isolated experiment DB created: `backend/ch6_eval.db`
- Reliable local experiment dataset: `dataset_id=3` (`sample_stops.csv`)
- Dataset 3 profile:
  - 12 geocoded stops
  - total demand `16`
  - average service time `7.83` min
  - workday windows span `09:00` to `18:00`
  - depot used for reruns: `1.3521, 103.8198`
- OD cache coverage at `08:00`, `day_of_week=6`:
  - dataset 1: `12/12` pairs (`100%`)
  - dataset 3: `156/156` pairs (`100%`)
  - dataset 4: `0/930` pairs (`0%`)

## Important Local Constraints

- `backend/app.db` has `0` rows in `actual_travel_times`.
- `backend/app.db` has an older `plans` schema snapshot; runtime compatibility columns are added on startup.
- `backend/data/ml_uplift/samples.csv` has `30` rows, but all rows are degenerate:
  - `static_duration_s = 180`
  - `duration_s = 180`
  - `congestion_factor = 1.0`
- `backend/app/ml_uplift/artifacts/` was empty before this run.
- Result: uplift evaluation is not meaningful locally without new Google-reference samples.

## Local ML Artifact Status

The DB registry originally pointed at `v20260216081956`, but that artifact path was not present on disk. For isolated reruns, the experiment DB was updated to register on-disk artifacts directly.

Distinct local model families screened against dataset 3:

| Version | Offline rows | Offline MAE | Mean predicted/fallback ratio on dataset 3 legs |
| --- | ---: | ---: | ---: |
| `v20260216105011` | 60 | 46.89 s | 4.70x |
| `v20260216103502` | 80 | 2.57 s | 7.40x |
| `v20260315045420274714` | 80 | 2.57 s | 7.40x |

Interpretation: the best-looking offline artifacts were badly miscalibrated for the cached Singapore OD matrix used by dataset 3.

## Fresh A/B Experiment Results

Baseline in this repo's A/B path: `fallback_v1`

Primary active-model rerun used: `v20260315045420274714`

| Scenario | Baseline makespan (s) | ML makespan (s) | Makespan delta | Baseline distance (m) | ML distance (m) | Distance delta | Served | On-time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Nominal: 2 vehicles, cap 20, 08:00-18:00 | 15,778 | 25,630 | -62.44% | 6,936.10 | 12,545.34 | -80.87% | 12/12 vs 12/12 | 1.00 vs 1.00 |
| Single vehicle, cap 20, 08:00-18:00 | 15,778 | 25,630 | -62.44% | 6,936.10 | 12,545.34 | -80.87% | 12/12 vs 12/12 | 1.00 vs 1.00 |
| Tight capacity: 2 vehicles, cap 8, 08:00-18:00 | 14,268 | 20,442 | -43.27% | 8,362.79 | 13,902.68 | -66.24% | 12/12 vs 12/12 | 1.00 vs 1.00 |
| Tighter day: 2 vehicles, cap 20, 09:00-17:00 | 12,178 | 22,040 | -80.98% | 6,936.10 | 12,545.34 | -80.87% | 12/12 vs 12/12 | 1.00 vs 1.00 |
| No drops allowed: 2 vehicles, cap 20, 08:00-18:00 | 15,778 | 25,630 | -62.44% | 6,936.10 | 12,545.34 | -80.87% | 12/12 vs 12/12 | 1.00 vs 1.00 |

`delta` is reported using the repo's own comparison convention where negative values mean the ML variant was worse for lower-is-better KPIs.

## Cross-Check Across Model Families

Nominal scenario (`2 vehicles`, `cap 20`, `08:00-18:00`):

| Model version | Offline MAE | ML makespan (s) | Makespan delta vs fallback | ML distance (m) | Distance delta vs fallback |
| --- | ---: | ---: | ---: | ---: | ---: |
| `v20260216105011` | 46.89 s | 18,788 | -19.08% | 15,447.02 | -122.70% |
| `v20260216103502` | 2.57 s | 25,630 | -62.44% | 12,545.34 | -80.87% |
| `v20260315045420274714` | 2.57 s | 25,630 | -62.44% | 12,545.34 | -80.87% |

Interpretation: under the only locally robust OD-backed scenario, every screened ML artifact underperformed the fallback baseline.

## What Can Be Claimed From Local Evidence

- Strongly supported now:
  - route-output persistence exists
  - baseline-vs-ML A/B experiments are runnable
  - scenario, route, makespan, distance, unserved-stop, and on-time KPIs are recoverable
- Weak or unsupported locally:
  - formal actual-vs-predicted travel-time evaluation
  - meaningful uplift evaluation
  - any claim that the local ML travel-time artifacts improved route quality on dataset 3

## Recommendation For Dissertation Use

- Use dataset 3 A/B reruns only if you are willing to report a negative result: locally, the ML travel-time artifacts did not improve planning KPIs.
- Do not use local uplift metrics as dissertation evidence without collecting new non-degenerate Google-reference samples.
- If you need positive ML evidence, you need one of:
  - production actual travel-time labels
  - a verified production model artifact aligned to the cached OD matrix
  - new controlled experiments after retraining/calibrating the travel-time model
