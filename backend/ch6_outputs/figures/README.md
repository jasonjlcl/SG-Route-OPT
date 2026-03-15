# Chapter 6 Figures

Generated from `backend/ch6_outputs/generate_ch6_figures.py`.

## Figure Set

1. `figure_ch6_01_makespan_by_scenario.svg`
   Makespan comparison across the five Dataset 3 rerun scenarios for the fallback baseline, the initial local ML artifact, and the calibrated local model.
2. `figure_ch6_02_distance_by_scenario.svg`
   Distance comparison across the same five scenarios.
3. `figure_ch6_03_makespan_change_vs_fallback.svg`
   Relative makespan change against the fallback baseline by scenario, contrasting the initial local ML regression with the calibrated-model recovery.
4. `figure_ch6_04_nominal_model_screening.svg`
   Nominal-scenario screening of existing local artifacts and retrained candidates, using makespan change versus fallback as the plotted outcome.

## Scenario Labels

- `S1`: nominal scenario, `2` vehicles, capacity `20`, `08:00-18:00`, drop visits allowed
- `S2`: single-vehicle scenario, capacity `20`, `08:00-18:00`, drop visits allowed
- `S3`: tight-capacity scenario, `2` vehicles, capacity `8`, `08:00-18:00`, drop visits allowed
- `S4`: shorter-workday scenario, `2` vehicles, capacity `20`, `09:00-17:00`, drop visits allowed
- `S5`: no-drop scenario, `2` vehicles, capacity `20`, `08:00-18:00`, drop visits not allowed

## Source Values

- Initial local evaluation summary:
  `backend/ch6_outputs/ch6_local_evaluation_2026-03-15.md`
- Retraining and rerun summary:
  `backend/ch6_outputs/ch6_retraining_rerun_summary_2026-03-15.md`
