#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
: "${GCS_BUCKET:?Set GCS_BUCKET (for example gs://route_app)}"

GCP_REGION="${GCP_REGION:-asia-southeast1}"
SERVICE_NAME="${SERVICE_NAME:-sg-route-opt-api}"
QUEUE_NAME="${CLOUD_TASKS_QUEUE:-route-jobs}"
SCHEDULER_JOB_NAME="${SCHEDULER_JOB_NAME:-route-ml-drift-weekly}"
IMAGE_URI="${IMAGE_URI:-gcr.io/${GCP_PROJECT_ID}/${SERVICE_NAME}:latest}"
API_SA_NAME="${API_SA_NAME:-route-app-api-sa}"
TASKS_SA_NAME="${TASKS_SA_NAME:-route-app-tasks-sa}"
FEATURE_VERTEX_AI="${FEATURE_VERTEX_AI:-false}"
VERTEX_MODEL_DISPLAY_NAME="${VERTEX_MODEL_DISPLAY_NAME:-route-time-regressor}"
ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-*}"
FRONTEND_BASE_URL="${FRONTEND_BASE_URL:-https://example-frontend.invalid}"
SCHEDULER_TOKEN="${SCHEDULER_TOKEN:-}"

echo "==> Configuring project ${GCP_PROJECT_ID} (${GCP_REGION})"
gcloud config set project "${GCP_PROJECT_ID}" >/dev/null

echo "==> Enabling required services"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudtasks.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  cloudscheduler.googleapis.com \
  aiplatform.googleapis.com >/dev/null

echo "==> Creating storage bucket if needed"
if ! gsutil ls "${GCS_BUCKET}" >/dev/null 2>&1; then
  gsutil mb -l "${GCP_REGION}" "${GCS_BUCKET}"
fi

echo "==> Creating service accounts"
if ! gcloud iam service-accounts describe "${API_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${API_SA_NAME}" --display-name="SG Route API SA" >/dev/null
fi
if ! gcloud iam service-accounts describe "${TASKS_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${TASKS_SA_NAME}" --display-name="SG Route Tasks SA" >/dev/null
fi

API_SA_EMAIL="${API_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
TASKS_SA_EMAIL="${TASKS_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Binding IAM roles (least-privilege baseline)"
gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:${API_SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" >/dev/null
gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:${API_SA_EMAIL}" \
  --role="roles/cloudtasks.enqueuer" >/dev/null
gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:${API_SA_EMAIL}" \
  --role="roles/aiplatform.user" >/dev/null
gcloud storage buckets add-iam-policy-binding "${GCS_BUCKET}" \
  --member="serviceAccount:${API_SA_EMAIL}" \
  --role="roles/storage.objectAdmin" >/dev/null

echo "==> Creating/updating secrets"
for SECRET_NAME in ONEMAP_EMAIL ONEMAP_PASSWORD MAPS_STATIC_API_KEY; do
  if ! gcloud secrets describe "${SECRET_NAME}" >/dev/null 2>&1; then
    gcloud secrets create "${SECRET_NAME}" --replication-policy="automatic" >/dev/null
  fi
  SECRET_VALUE="${!SECRET_NAME:-}"
  if [[ -n "${SECRET_VALUE}" ]]; then
    printf '%s' "${SECRET_VALUE}" | gcloud secrets versions add "${SECRET_NAME}" --data-file=- >/dev/null
  fi
done

echo "==> Building container image"
gcloud builds submit --tag "${IMAGE_URI}" . >/dev/null

echo "==> Deploying Cloud Run service (min=0, max=1)"
gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE_URI}" \
  --region="${GCP_REGION}" \
  --platform=managed \
  --service-account="${API_SA_EMAIL}" \
  --allow-unauthenticated \
  --min-instances=0 \
  --max-instances=1 \
  --memory=2Gi \
  --cpu=1 \
  --timeout=900 \
  --set-env-vars="APP_ENV=prod,GCP_PROJECT_ID=${GCP_PROJECT_ID},GCP_REGION=${GCP_REGION},GCS_BUCKET=${GCS_BUCKET},CLOUD_TASKS_QUEUE=${QUEUE_NAME},CLOUD_TASKS_SERVICE_ACCOUNT=${TASKS_SA_EMAIL},FEATURE_VERTEX_AI=${FEATURE_VERTEX_AI},VERTEX_MODEL_DISPLAY_NAME=${VERTEX_MODEL_DISPLAY_NAME},TASKS_AUTH_REQUIRED=true,ALLOWED_ORIGINS=${ALLOWED_ORIGINS},FRONTEND_BASE_URL=${FRONTEND_BASE_URL}" \
  --set-secrets="ONEMAP_EMAIL=ONEMAP_EMAIL:latest,ONEMAP_PASSWORD=ONEMAP_PASSWORD:latest,MAPS_STATIC_API_KEY=MAPS_STATIC_API_KEY:latest" >/dev/null

SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" --region="${GCP_REGION}" --format='value(status.url)')"
TASKS_AUDIENCE="${SERVICE_URL}/tasks/handle"
DRIFT_URL="${SERVICE_URL}/api/v1/ml/drift-report"

echo "==> Updating Cloud Run runtime URLs"
gcloud run services update "${SERVICE_NAME}" \
  --region="${GCP_REGION}" \
  --set-env-vars="APP_BASE_URL=${SERVICE_URL},CLOUD_TASKS_AUDIENCE=${TASKS_AUDIENCE},SCHEDULER_TOKEN=${SCHEDULER_TOKEN}" >/dev/null

echo "==> Creating/updating Cloud Tasks queue"
if ! gcloud tasks queues describe "${QUEUE_NAME}" --location="${GCP_REGION}" >/dev/null 2>&1; then
  gcloud tasks queues create "${QUEUE_NAME}" \
    --location="${GCP_REGION}" \
    --max-concurrent-dispatches=1 \
    --max-dispatches-per-second=1 >/dev/null
else
  gcloud tasks queues update "${QUEUE_NAME}" \
    --location="${GCP_REGION}" \
    --max-concurrent-dispatches=1 \
    --max-dispatches-per-second=1 >/dev/null
fi

echo "==> Allowing Cloud Tasks principal to invoke /tasks/handle"
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${GCP_REGION}" \
  --member="serviceAccount:${TASKS_SA_EMAIL}" \
  --role="roles/run.invoker" >/dev/null

echo "==> Creating/updating weekly Cloud Scheduler drift check"
HEADER_ARG=()
if [[ -n "${SCHEDULER_TOKEN}" ]]; then
  HEADER_ARG=(--headers="X-Scheduler-Token=${SCHEDULER_TOKEN}")
fi

if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" --location="${GCP_REGION}" >/dev/null 2>&1; then
  gcloud scheduler jobs delete "${SCHEDULER_JOB_NAME}" --location="${GCP_REGION}" --quiet >/dev/null
fi

gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
  --location="${GCP_REGION}" \
  --schedule="0 3 * * 1" \
  --http-method=POST \
  --uri="${DRIFT_URL}?trigger_retrain=true" \
  --oidc-service-account-email="${TASKS_SA_EMAIL}" \
  --oidc-token-audience="${DRIFT_URL}" \
  "${HEADER_ARG[@]}" >/dev/null

cat <<EOF
Deployment complete.
Cloud Run URL: ${SERVICE_URL}
Cloud Tasks queue: ${QUEUE_NAME}
Scheduler job: ${SCHEDULER_JOB_NAME}
EOF
