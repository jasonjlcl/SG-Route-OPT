# Chapter 6 New Dataset Evaluation Summary

Date: 2026-03-15

## Setup

- Base DB clone source: `backend\ch6_retrain_eval.db`
- Work DB used for this run: `backend\ch6_experiments_10_eval.db`
- New input files evaluated: `10`
- Solver time limit per run: `8` seconds
- Scenario IDs executed: `S1`
- OneMap credential mock mode: `False`
- Authenticated OneMap routing was available for this run, so route durations were derived from live OneMap routing responses rather than the repo's mock fallback path.

## Dataset Import and Geocoding

| File | Dataset ID | Stops | Total demand | Total service min | Geocode success | Geocode failed | Geocode sources |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `stops_experiment_1.csv` | 8 | 8 | 15 | 53 | 8 | 0 | onemap=8 |
| `stops_experiment_2.csv` | 9 | 8 | 15 | 53 | 8 | 0 | manual_search=2, onemap=6 |
| `stops_experiment_3.csv` | 10 | 8 | 15 | 53 | 8 | 0 | onemap=8 |
| `stops_experiment_4.csv` | 11 | 8 | 15 | 53 | 8 | 0 | manual_search=2, onemap=6 |
| `stops_experiment_5.csv` | 12 | 8 | 15 | 53 | 8 | 0 | manual_search=1, onemap=7 |
| `stops_experiment_6.csv` | 13 | 8 | 15 | 53 | 8 | 0 | manual_search=1, onemap=7 |
| `stops_experiment_7.csv` | 14 | 8 | 15 | 53 | 8 | 0 | manual_search=1, onemap=7 |
| `stops_experiment_8.csv` | 15 | 8 | 15 | 53 | 7 | 1 | onemap=7, unknown=1 |
| `stops_experiment_9.csv` | 16 | 8 | 15 | 53 | 8 | 0 | onemap=8 |
| `stops_experiment_10.csv` | 17 | 7 | 13 | 46 | 7 | 0 | onemap=7 |

## Aggregate Scenario Results

| Scenario | Datasets | Initial mean makespan improvement | Initial wins | Calibrated mean makespan improvement | Calibrated wins | Initial mean distance improvement | Calibrated mean distance improvement |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S1 Nominal | 10 | +1.78% | 4/10 | +5.50% | 10/10 | -14.84% | -14.71% |

## Nominal Scenario Detail

| File | Dataset ID | Baseline makespan (s) | Initial makespan improvement | Calibrated makespan improvement | Baseline distance (m) | Initial distance improvement | Calibrated distance improvement |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `stops_experiment_1.csv` | 8 | 15366 | +11.13% | +10.90% | 99616.00 | -12.81% | -23.36% |
| `stops_experiment_2.csv` | 9 | 18037 | -3.41% | +1.39% | 86779.00 | -23.29% | -23.29% |
| `stops_experiment_3.csv` | 10 | 23471 | +5.69% | +2.52% | 110601.00 | -3.45% | -24.92% |
| `stops_experiment_4.csv` | 11 | 24357 | -2.79% | +2.52% | 79829.00 | -8.59% | +4.29% |
| `stops_experiment_5.csv` | 12 | 29042 | -5.61% | +1.86% | 95541.00 | -25.21% | -52.40% |
| `stops_experiment_6.csv` | 13 | 15632 | +11.62% | +17.20% | 83052.00 | +0.00% | -6.22% |
| `stops_experiment_7.csv` | 14 | 19473 | +11.21% | +10.40% | 76735.00 | -31.42% | -11.99% |
| `stops_experiment_8.csv` | 15 | 21252 | -3.38% | +2.27% | 50377.00 | -0.48% | -9.21% |
| `stops_experiment_9.csv` | 16 | 25007 | -2.26% | +2.96% | 29267.00 | -30.92% | +0.00% |
| `stops_experiment_10.csv` | 17 | 27942 | -4.40% | +2.98% | 25619.00 | -12.22% | -0.00% |

## Interpretation

- These 10 datasets expand the local rerun set under authenticated OneMap routing, but they are still a separate evidence tier from the earlier OD-cache-backed Dataset 3 study because they rely on newly imported local CSV datasets rather than the original cache-backed evaluation set.
- The critical question for this run is not absolute field realism but relative sensitivity: whether the harmful original local model still underperforms the fallback baseline, and whether the calibrated model remains directionally better.
- Use this file together with the JSON output for exact per-dataset, per-scenario results.
