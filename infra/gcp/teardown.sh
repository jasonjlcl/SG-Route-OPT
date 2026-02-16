#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"

GCP_REGION="${GCP_REGION:-asia-southeast1}"
SERVICE_NAME="${SERVICE_NAME:-sg-route-opt-api}"
QUEUE_NAME="${CLOUD_TASKS_QUEUE:-route-jobs}"
SCHEDULER_JOB_NAME="${SCHEDULER_JOB_NAME:-route-ml-drift-weekly}"
API_SA_NAME="${API_SA_NAME:-route-app-api-sa}"
TASKS_SA_NAME="${TASKS_SA_NAME:-route-app-tasks-sa}"
GCS_BUCKET="${GCS_BUCKET:-}"

gcloud config set project "${GCP_PROJECT_ID}" >/dev/null

echo "==> Deleting scheduler job"
gcloud scheduler jobs delete "${SCHEDULER_JOB_NAME}" --location="${GCP_REGION}" --quiet >/dev/null 2>&1 || true

echo "==> Deleting Cloud Tasks queue"
gcloud tasks queues delete "${QUEUE_NAME}" --location="${GCP_REGION}" --quiet >/dev/null 2>&1 || true

echo "==> Deleting Cloud Run service"
gcloud run services delete "${SERVICE_NAME}" --region="${GCP_REGION}" --quiet >/dev/null 2>&1 || true

echo "==> Deleting service accounts"
gcloud iam service-accounts delete "${API_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" --quiet >/dev/null 2>&1 || true
gcloud iam service-accounts delete "${TASKS_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" --quiet >/dev/null 2>&1 || true

if [[ -n "${GCS_BUCKET}" ]]; then
  echo "==> Removing bucket objects (${GCS_BUCKET})"
  gsutil -m rm -r "${GCS_BUCKET}/**" >/dev/null 2>&1 || true
fi

echo "Teardown complete."
