# Phase 7 Monitoring Assets

This folder contains deployable alert and dashboard templates for Phase 7:

- `alert_policies/*.json`
- `dashboard/sg_route_opt_core_slo_dashboard.json`

Use `infra/gcp/monitoring/apply_phase7_monitoring.sh` to create/update:

- logs-based metrics
- alert policies
- dashboard

## Required Environment

- `GCP_PROJECT_ID`

Optional:

- `SERVICE_NAME` (default: `sg-route-opt-api`)
- `CLOUD_TASKS_QUEUE` (default: `route-jobs`)
- `MONITORING_NOTIFICATION_CHANNELS` (comma-separated channel IDs)

## Staging Validation Drill

To verify incidents fire in staging:

1. Apply monitoring assets
- `bash infra/gcp/monitoring/apply_phase7_monitoring.sh`

2. Slow optimize latency signal
- Set `OPTIMIZE_LATENCY_WARN_SECONDS=1` on staging service revision.
- Run an optimize job.
- Confirm `OPTIMIZE_LATENCY_SLOW` log appears and corresponding policy enters incident state.

3. Stale lock reclaim signal
- Temporarily set:
  - `PIPELINE_RETRY_DRILL_STEP=BUILD_MATRIX`
  - `PIPELINE_RETRY_DRILL_DELAY_SECONDS=90`
- Run optimize in cloud mode and verify `PIPELINE_STALE_LOCK_RECLAIMED` appears.
- Confirm stale-lock alert incident opens.

4. Fallback spike signal
- Trigger API fallback path (for example, force Google traffic failure and run optimize).
- Confirm fallback warning logs and fallback-rate alert behavior.

5. Signed URL failure signal
- Force signed URL generation failure path (for example, invalid service-account signing setup) and run export.
- Confirm signed URL failure logs and alert behavior.

6. Cloud Tasks retry/failure signals
- Use a temporary task handler failure drill (`/tasks/handle` returns 5xx for selected step).
- Confirm queue retry delay/failure policies observe the event window.

## Tuned Thresholds (February 22, 2026)

Based on staging drill behavior (burst queue loads and controlled retry injections), the default alert thresholds were tuned to reduce single-event noise while preserving sustained-signal detection:

- Cloud Tasks queue depth: `> 80` for `10m` (was `> 40`).
- Cloud Tasks retry delay p95: `> 300000 ms` for `10m` (was `> 120000 ms`).
- Cloud Tasks failure attempt rate: `> 0.05/s` for `10m` (was `> 0.02/s` for `5m`).
- Fallback event rate: `> 0.05/s` for `10m` (was `> 0.03/s`).
- Stale lock reclaimed count: `> 1` in `10m` (was `> 0`).
- Slow optimize count: `> 1` in `10m` (was `> 0`).
