# Sensitivity Analysis Summary

Date: 2026-04-03

## Base Case

- Dataset input: `3`
- Nominal base case: `num_vehicles=2`, `vehicle_capacity=20`, `workday=08:00-18:00`, `allow_drop_visits=true`
- Stop service times: original dataset values at `1.0x` scale
- Stop time windows: original dataset values
- Travel-time variants: `fallback_baseline` and calibrated ML model `v20260315063821017757`
- Solver time limit per run: `8` seconds
- Depot: `(1.3521, 103.8198)`

## Factors Varied

| Factor | Values |
| --- | --- |
| Fleet size | `1`, `2`, `3` vehicles |
| Vehicle capacity | `8`, `20`, `30` parcels |
| Workday duration | `08:00-18:00`, `09:00-17:00` |
| Service time scaling | `1.0x`, `1.2x` |
| Time-window tightness | `original`, `tighter` |
| Travel-time source | paired `fallback_baseline` and calibrated ML for every scenario |

## Key Findings

- Calibrated-vs-fallback scenario pairs: `13`
- Calibrated model improved makespan in `12/13` scenario pairs and improved distance in `0/13` pairs.
- Mean calibrated-minus-fallback makespan delta: `-207.85` seconds.
- Mean calibrated-minus-fallback distance delta: `82.69` m.
- Mean calibrated-minus-fallback solve-time delta: `0.000` seconds.

### Largest Makespan Shifts by Factor

| Travel-time source | Factor | Scenario | Value | Makespan delta vs source base case (s) | Distance delta vs source base case (m) |
| --- | --- | --- | --- | ---: | ---: |
| calibrated_ml | fleet_size | FLEET_1 | 1 | 0.00 | 0.00 |
| calibrated_ml | service_time_scale | SERVICE_1_2X | 1.2x | 480.00 | 0.00 |
| calibrated_ml | time_window_tightness | TW_TIGHTER | tighter | 3832.00 | 1977.00 |
| calibrated_ml | vehicle_capacity | CAPACITY_8 | 8 | -1932.00 | 3266.00 |
| calibrated_ml | workday_duration | WORKDAY_0900_1700 | 09:00-17:00 | -3600.00 | 0.00 |
| fallback_baseline | fleet_size | FLEET_1 | 1 | 0.00 | 0.00 |
| fallback_baseline | service_time_scale | SERVICE_1_2X | 1.2x | 480.00 | 0.00 |
| fallback_baseline | time_window_tightness | TW_TIGHTER | tighter | 1140.00 | 1077.00 |
| fallback_baseline | vehicle_capacity | CAPACITY_8 | 8 | -2024.00 | 3091.00 |
| fallback_baseline | workday_duration | WORKDAY_0900_1700 | 09:00-17:00 | -3600.00 | 0.00 |

## Scenario Results

| Scenario | Source | Factor | Value | Makespan (s) | Distance (m) | Served | On-time rate | Late | Dropped | Solver status | Solve time (s) |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| BASE_CASE | fallback_baseline | base_case | nominal | 15760.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.002 |
| BASE_CASE | calibrated_ml | base_case | nominal | 15338.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.002 |
| FLEET_1 | fallback_baseline | fleet_size | 1 | 15760.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.000 |
| FLEET_1 | calibrated_ml | fleet_size | 1 | 15338.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.001 |
| FLEET_2 | fallback_baseline | fleet_size | 2 | 15760.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.000 |
| FLEET_2 | calibrated_ml | fleet_size | 2 | 15338.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.001 |
| FLEET_3 | fallback_baseline | fleet_size | 3 | 15760.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.000 |
| FLEET_3 | calibrated_ml | fleet_size | 3 | 15338.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.000 |
| CAPACITY_8 | fallback_baseline | vehicle_capacity | 8 | 13736.00 | 21450.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.000 |
| CAPACITY_8 | calibrated_ml | vehicle_capacity | 8 | 13406.00 | 21625.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.001 |
| CAPACITY_20 | fallback_baseline | vehicle_capacity | 20 | 15760.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.000 |
| CAPACITY_20 | calibrated_ml | vehicle_capacity | 20 | 15338.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.001 |
| CAPACITY_30 | fallback_baseline | vehicle_capacity | 30 | 15760.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.002 |
| CAPACITY_30 | calibrated_ml | vehicle_capacity | 30 | 15338.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.000 |
| WORKDAY_0800_1800 | fallback_baseline | workday_duration | 08:00-18:00 | 15760.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.001 |
| WORKDAY_0800_1800 | calibrated_ml | workday_duration | 08:00-18:00 | 15338.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.001 |
| WORKDAY_0900_1700 | fallback_baseline | workday_duration | 09:00-17:00 | 12160.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.001 |
| WORKDAY_0900_1700 | calibrated_ml | workday_duration | 09:00-17:00 | 11738.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.000 |
| SERVICE_1_0X | fallback_baseline | service_time_scale | 1.0x | 15760.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.000 |
| SERVICE_1_0X | calibrated_ml | service_time_scale | 1.0x | 15338.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.001 |
| SERVICE_1_2X | fallback_baseline | service_time_scale | 1.2x | 16240.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.001 |
| SERVICE_1_2X | calibrated_ml | service_time_scale | 1.2x | 15818.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.001 |
| TW_ORIGINAL | fallback_baseline | time_window_tightness | original | 15760.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.001 |
| TW_ORIGINAL | calibrated_ml | time_window_tightness | original | 15338.00 | 18359.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.000 |
| TW_TIGHTER | fallback_baseline | time_window_tightness | tighter | 16900.00 | 19436.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.000 |
| TW_TIGHTER | calibrated_ml | time_window_tightness | tighter | 19170.00 | 20336.60 | 12/12 | 1.00 | 0 | 0 | SUCCESS | 8.000 |

## Limitations and Assumptions

- Service-time scaling was applied by editing copied stop rows in an isolated work database; the source dataset was not modified.
- The `tighter` time-window mode trims explicit stop windows by 60 minutes in total while preserving at least 60 minutes of width; stops without explicit time windows are left unchanged.
- Travel-time source was evaluated as paired fallback-versus-calibrated runs under the same operational settings.
- `solve_time_seconds` measures the OR-Tools solver call only. Matrix building and prediction time are not included in that field.
- `late_stops` and `dropped_stops` are limited to what the existing VRPTW evaluation path exposes.
