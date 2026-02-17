# Sample Data Pack

Files:
- `stops_valid_small.csv`: clean 12-stop dataset for quick happy-path testing.
- `stops_mixed_invalid.csv`: includes intentional bad rows for validation and error-log testing.
- `stops_valid_30.csv`: larger valid dataset for longer geocode/optimize pipeline runs.

Suggested test flow:
1. Upload `stops_valid_small.csv` and run full pipeline.
2. Upload `stops_mixed_invalid.csv` with and without `exclude_invalid=true`.
3. Upload `stops_valid_30.csv` and watch async progress + export generation timing.
