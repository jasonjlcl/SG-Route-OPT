# Sample Data Pack

Files:
- `stops_valid_small.csv`: clean 12-stop dataset for quick happy-path testing.
- `stops_mixed_invalid.csv`: includes intentional bad rows for validation and error-log testing.
- `stops_valid_30.csv`: larger valid dataset for longer geocode/optimize pipeline runs.
- `stops_valid_quick_8.csv`: smallest clean set for fast upload -> geocode -> optimize checks.
- `stops_tight_time_windows_12.csv`: narrow time windows to test lateness/feasibility behavior.
- `stops_capacity_stress_15.csv`: higher demand values to test capacity constraints.
- `stops_phone_edge_cases_10.csv`: phone-number formatting edge cases for validation/UI checks.

Suggested test flow:
1. Upload `stops_valid_small.csv` and run full pipeline.
2. Upload `stops_mixed_invalid.csv` with and without `exclude_invalid=true`.
3. Upload `stops_valid_30.csv` and watch async progress + export generation timing.
4. Upload `stops_tight_time_windows_12.csv` and inspect time-window violations/suggestions.
5. Upload `stops_capacity_stress_15.csv` with smaller fleet capacity to force capacity pressure.
6. Upload `stops_phone_edge_cases_10.csv` to test phone validation and call-button behavior.
