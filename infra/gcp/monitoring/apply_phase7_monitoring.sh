#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"

GCLOUD_BIN="${GCLOUD_BIN:-gcloud}"
SERVICE_NAME="${SERVICE_NAME:-sg-route-opt-api}"
QUEUE_NAME="${CLOUD_TASKS_QUEUE:-route-jobs}"
MONITORING_NOTIFICATION_CHANNELS="${MONITORING_NOTIFICATION_CHANNELS:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASE7_DIR="${SCRIPT_DIR}/phase7"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

render_template() {
  local source_file="$1"
  local target_file="$2"
  sed \
    -e "s/__SERVICE_NAME__/${SERVICE_NAME}/g" \
    -e "s/__QUEUE_NAME__/${QUEUE_NAME}/g" \
    "${source_file}" > "${target_file}"
}

upsert_logging_metric() {
  local metric_name="$1"
  local description="$2"
  local log_filter="$3"
  if "${GCLOUD_BIN}" logging metrics describe "${metric_name}" >/dev/null 2>&1; then
    "${GCLOUD_BIN}" logging metrics update "${metric_name}" \
      --description="${description}" \
      --log-filter="${log_filter}" >/dev/null
  else
    "${GCLOUD_BIN}" logging metrics create "${metric_name}" \
      --description="${description}" \
      --log-filter="${log_filter}" >/dev/null
  fi
}

upsert_policy_from_template() {
  local template_path="$1"
  local display_name="$2"
  local rendered_path="${TMP_DIR}/$(basename "${template_path}")"

  render_template "${template_path}" "${rendered_path}"

  local policy_name
  policy_name="$("${GCLOUD_BIN}" monitoring policies list \
    --filter="displayName=\"${display_name}\"" \
    --format="value(name)" \
    --limit=1)"

  if [[ -n "${policy_name}" ]]; then
    "${GCLOUD_BIN}" monitoring policies update "${policy_name}" --policy-from-file="${rendered_path}" >/dev/null
  else
    "${GCLOUD_BIN}" monitoring policies create --policy-from-file="${rendered_path}" >/dev/null
    policy_name="$("${GCLOUD_BIN}" monitoring policies list \
      --filter="displayName=\"${display_name}\"" \
      --format="value(name)" \
      --limit=1)"
  fi

  if [[ -n "${MONITORING_NOTIFICATION_CHANNELS}" && -n "${policy_name}" ]]; then
    "${GCLOUD_BIN}" monitoring policies update "${policy_name}" \
      --set-notification-channels="${MONITORING_NOTIFICATION_CHANNELS}" >/dev/null
  fi
}

replace_dashboard_from_template() {
  local template_path="$1"
  local display_name="$2"
  local rendered_path="${TMP_DIR}/$(basename "${template_path}")"

  render_template "${template_path}" "${rendered_path}"

  local dashboard_name
  dashboard_name="$("${GCLOUD_BIN}" monitoring dashboards list \
    --filter="displayName=\"${display_name}\"" \
    --format="value(name)" \
    --limit=1)"

  if [[ -n "${dashboard_name}" ]]; then
    "${GCLOUD_BIN}" monitoring dashboards delete "${dashboard_name}" --quiet >/dev/null
  fi
  "${GCLOUD_BIN}" monitoring dashboards create --config-from-file="${rendered_path}" >/dev/null
}

echo "==> Configuring project ${GCP_PROJECT_ID}"
"${GCLOUD_BIN}" config set project "${GCP_PROJECT_ID}" >/dev/null

echo "==> Ensuring Phase 7 logs-based metrics"
upsert_logging_metric \
  "sg_route_opt_db_lock_retry_count" \
  "Count of DB_LOCK_RETRY warnings emitted by API workers." \
  "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND textPayload:\"DB_LOCK_RETRY\""

upsert_logging_metric \
  "sg_route_opt_fallback_event_count" \
  "Count of ETA/routing fallback warning events." \
  "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND (textPayload:\"Google ETA fallback activated\" OR textPayload:\"Google resequence fallback activated\" OR textPayload:\"OneMap route fallback to heuristic estimate\")"

upsert_logging_metric \
  "sg_route_opt_signed_url_failure_count" \
  "Count of signed URL generation failures." \
  "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND (textPayload:\"Failed to generate signed URL; returning no URL\" OR textPayload:\"Failed to generate signed URL with IAM signing fallback\")"

upsert_logging_metric \
  "sg_route_opt_optimize_slow_count" \
  "Count of optimize runs exceeding OPTIMIZE_LATENCY_WARN_SECONDS." \
  "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND textPayload:\"OPTIMIZE_LATENCY_SLOW\""

upsert_logging_metric \
  "sg_route_opt_stale_lock_reclaimed_count" \
  "Count of stale pipeline locks reclaimed during step execution." \
  "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND textPayload:\"PIPELINE_STALE_LOCK_RECLAIMED\""

upsert_logging_metric \
  "sg_route_opt_optimize_complete_count" \
  "Count of optimize pipeline completion events." \
  "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND textPayload:\"OPTIMIZE_PIPELINE_COMPLETE\""

echo "==> Ensuring Phase 7 alert policies"
upsert_policy_from_template \
  "${PHASE7_DIR}/alert_policies/cloud_tasks_queue_depth_high.json" \
  "sg-route-opt - Cloud Tasks queue depth high (possible stuck jobs)"
upsert_policy_from_template \
  "${PHASE7_DIR}/alert_policies/cloud_tasks_retry_delay_high.json" \
  "sg-route-opt - Cloud Tasks retry delay p95 high"
upsert_policy_from_template \
  "${PHASE7_DIR}/alert_policies/cloud_tasks_failure_rate_high.json" \
  "sg-route-opt - Cloud Tasks failure attempt rate high"
upsert_policy_from_template \
  "${PHASE7_DIR}/alert_policies/db_lock_retry_spike.json" \
  "sg-route-opt - DB lock retry spike"
upsert_policy_from_template \
  "${PHASE7_DIR}/alert_policies/fallback_event_rate_spike.json" \
  "sg-route-opt - Fallback event rate spike"
upsert_policy_from_template \
  "${PHASE7_DIR}/alert_policies/signed_url_failures_detected.json" \
  "sg-route-opt - Signed URL failures detected"
upsert_policy_from_template \
  "${PHASE7_DIR}/alert_policies/optimize_latency_slow_detected.json" \
  "sg-route-opt - Optimize latency slow runs detected"
upsert_policy_from_template \
  "${PHASE7_DIR}/alert_policies/stale_lock_reclaimed_detected.json" \
  "sg-route-opt - Pipeline stale lock reclaimed"

echo "==> Ensuring Phase 7 dashboard"
replace_dashboard_from_template \
  "${PHASE7_DIR}/dashboard/sg_route_opt_core_slo_dashboard.json" \
  "sg-route-opt - Core SLO dashboard"

echo "Phase 7 monitoring applied."
