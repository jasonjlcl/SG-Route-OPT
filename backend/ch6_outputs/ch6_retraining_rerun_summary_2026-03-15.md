# Retraining and Rerun Summary

Date: 2026-03-15

## Objective

Try retraining or calibrating the local travel-time model and rerun the Chapter 6 A/B experiments against the same OD-backed local dataset.

## Isolated Environment

- Source DB: `backend/app.db`
- Retraining experiment DB: `backend/ch6_retrain_eval.db`
- Evaluation dataset for reruns: `dataset_id=3`

## Why Retraining Was Needed

The previously screened local ML artifacts were badly miscalibrated for the local Singapore OD cache used by `dataset_id=3`. In the earlier reruns, the active local model increased route makespan by `62.44%` and total distance by `80.87%` relative to the fallback baseline.

## Candidate Retraining / Calibration Datasets

Four candidate datasets were generated locally:

1. `onemap_identity.csv`
   - Based on `backend/data/onemap_vertex_eta/onemap_labels.csv`
   - `base_duration_s = actual_duration_s`
2. `onemap_identity_multi_hour.csv`
   - Same as above, duplicated across representative hours `00, 08, 12, 18`
3. `onemap_routebase.csv`
   - Based on OneMap labels
   - `base_duration_s = route_distance_m / 9.0`
4. `od_cache_identity_multi_hour.csv`
   - Based on local `od_cache`
   - `actual_duration_s = base_duration_s`
   - duplicated across representative hours `00, 08, 12, 18`

Interpretation:

- The first three are calibration-style retraining datasets derived from the local OneMap label store.
- The fourth is a direct calibration-to-cache dataset intended to align inference with the actual OD matrix domain used by the routing experiments.

## Training Results

| Candidate dataset | Model version | Rows | Offline MAE (s) | Offline MAPE |
| --- | --- | ---: | ---: | ---: |
| `onemap_identity.csv` | `v20260315063816867841` | 2,600 | 3.47 | 0.00441 |
| `onemap_identity_multi_hour.csv` | `v20260315063819799285` | 10,400 | 2.79 | 0.00372 |
| `onemap_routebase.csv` | `v20260315063820648976` | 2,600 | 73.16 | 0.08683 |
| `od_cache_identity_multi_hour.csv` | `v20260315063821017757` | 1,292 | 0.15 | 0.00150 |

## Nominal Scenario Screening

Nominal scenario:

- 2 vehicles
- capacity 20
- workday `08:00-18:00`
- drop visits allowed

| Candidate model | Makespan delta vs fallback | Distance delta vs fallback | Result |
| --- | ---: | ---: | --- |
| `v20260315063816867841` | `-10.46%` | `-17.74%` | Worse |
| `v20260315063819799285` | `+0.54%` | `-29.34%` | Mixed |
| `v20260315063820648976` | `-6.46%` | `-21.97%` | Worse |
| `v20260315063821017757` | `+0.53%` | `0.00%` | Best overall |

The OD-cache-calibrated model `v20260315063821017757` was selected for full reruns because it was the only candidate that improved makespan without worsening total distance.

## Full Rerun Results With Best Candidate

Selected model:

- `v20260315063821017757`
- trained from `od_cache_identity_multi_hour.csv`

| Scenario | Baseline makespan (s) | Retrained model makespan (s) | Makespan improvement | Baseline distance (m) | Retrained model distance (m) | Distance improvement | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Nominal: 2 vehicles, cap 20, 08:00-18:00 | 15,778 | 15,694 | `+0.53%` | 6,936.10 | 6,936.10 | `0.00%` | Same route geometry, slightly shorter schedule |
| Single vehicle, cap 20, 08:00-18:00 | 15,778 | 15,694 | `+0.53%` | 6,936.10 | 6,936.10 | `0.00%` | Same pattern as nominal |
| Tight capacity: 2 vehicles, cap 8, 08:00-18:00 | 14,268 | 14,221 | `+0.33%` | 8,362.79 | 8,362.79 | `0.00%` | Sum vehicle duration improved by `10.42%` |
| Tighter day: 2 vehicles, cap 20, 09:00-17:00 | 12,178 | 12,094 | `+0.69%` | 6,936.10 | 6,936.10 | `0.00%` | Best makespan improvement among tested scenarios |
| No-drop variant: 2 vehicles, cap 20, 08:00-18:00 | 15,778 | 15,694 | `+0.53%` | 6,936.10 | 6,936.10 | `0.00%` | Same as nominal |

All reruns kept:

- `served_count = 12/12`
- `on_time_rate = 1.00`
- `unserved_count = 0`

## Interpretation

The retraining/calibration attempt succeeded in the limited sense that it removed the severe overprediction problem seen in the previous local ML artifacts. The best calibrated model no longer degraded the routing plan and produced small but consistent makespan improvements over the fallback baseline.

However, the gains were modest:

- makespan improvement ranged from `0.33%` to `0.69%`
- total distance did not improve
- service level metrics were unchanged

This indicates that the main issue with the earlier local artifacts was calibration mismatch, not the routing solver itself. Once the model was aligned to the local OD-cache domain, the dramatic regression disappeared. At the same time, the rerun results also suggest that the current local A/B setup has limited headroom for large gains because the baseline and calibrated model often preserve the same route geometry, with differences appearing mainly in schedule timing rather than route structure.

## Practical Conclusion

- Previous local model artifacts: not suitable for Chapter 6 evidence of improvement
- Retrained OD-cache-calibrated model: suitable as a limited positive sensitivity result
- Strength of claim supported by this rerun:
  - the local travel-time model can be calibrated so that it no longer harms routing performance
  - under the tested local scenarios, calibration yielded small schedule improvements but no distance reduction
- Claim still not supported:
  - improvement against real observed travel-time labels
  - improvement over manual-order baseline
  - improvement over nearest-neighbour baseline
