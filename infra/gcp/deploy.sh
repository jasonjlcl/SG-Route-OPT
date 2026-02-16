#!/usr/bin/env bash
set -euo pipefail
set -f

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
GCLOUD_BIN="${GCLOUD_BIN:-gcloud}"

echo "==> Configuring project ${GCP_PROJECT_ID} (${GCP_REGION})"
"${GCLOUD_BIN}" config set project "${GCP_PROJECT_ID}" >/dev/null

echo "==> Enabling required services"
"${GCLOUD_BIN}" services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudtasks.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  cloudscheduler.googleapis.com \
  aiplatform.googleapis.com >/dev/null

echo "==> Creating storage bucket if needed"
if ! "${GCLOUD_BIN}" storage ls "${GCS_BUCKET}" >/dev/null 2>&1; then
  "${GCLOUD_BIN}" storage buckets create "${GCS_BUCKET}" --location="${GCP_REGION}" >/dev/null
fi

echo "==> Creating service accounts"
if ! "${GCLOUD_BIN}" iam service-accounts describe "${API_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1; then
  "${GCLOUD_BIN}" iam service-accounts create "${API_SA_NAME}" --display-name=SG-Route-API-SA >/dev/null
fi
if ! "${GCLOUD_BIN}" iam service-accounts describe "${TASKS_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1; then
  "${GCLOUD_BIN}" iam service-accounts create "${TASKS_SA_NAME}" --display-name=SG-Route-Tasks-SA >/dev/null
fi

API_SA_EMAIL="${API_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
TASKS_SA_EMAIL="${TASKS_SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Binding IAM roles (least-privilege baseline)"
"${GCLOUD_BIN}" projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:${API_SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" >/dev/null
"${GCLOUD_BIN}" projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:${API_SA_EMAIL}" \
  --role="roles/cloudtasks.enqueuer" >/dev/null
"${GCLOUD_BIN}" projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:${API_SA_EMAIL}" \
  --role="roles/aiplatform.user" >/dev/null
"${GCLOUD_BIN}" iam service-accounts add-iam-policy-binding "${API_SA_EMAIL}" \
  --member="serviceAccount:${API_SA_EMAIL}" \
  --role="roles/iam.serviceAccountTokenCreator" >/dev/null
"${GCLOUD_BIN}" iam service-accounts add-iam-policy-binding "${TASKS_SA_EMAIL}" \
  --member="serviceAccount:${API_SA_EMAIL}" \
  --role="roles/iam.serviceAccountUser" >/dev/null
"${GCLOUD_BIN}" storage buckets add-iam-policy-binding "${GCS_BUCKET}" \
  --member="serviceAccount:${API_SA_EMAIL}" \
  --role="roles/storage.objectAdmin" >/dev/null

echo "==> Creating/updating secrets"
SECRET_BINDINGS=()
for SECRET_NAME in ONEMAP_EMAIL ONEMAP_PASSWORD MAPS_STATIC_API_KEY; do
  if ! "${GCLOUD_BIN}" secrets describe "${SECRET_NAME}" >/dev/null 2>&1; then
    "${GCLOUD_BIN}" secrets create "${SECRET_NAME}" --replication-policy="automatic" >/dev/null
  fi
  SECRET_VALUE="${!SECRET_NAME:-}"
  if [[ -n "${SECRET_VALUE}" ]]; then
    printf '%s' "${SECRET_VALUE}" | "${GCLOUD_BIN}" secrets versions add "${SECRET_NAME}" --data-file=- >/dev/null
    SECRET_BINDINGS+=("${SECRET_NAME}=${SECRET_NAME}:latest")
  fi
done

echo "==> Building container image"
TEMP_DOCKERFILE_CREATED=false
if [[ ! -f "./Dockerfile" ]]; then
  cp ./backend/Dockerfile ./Dockerfile
  TEMP_DOCKERFILE_CREATED=true
fi

"${GCLOUD_BIN}" builds submit --tag "${IMAGE_URI}" . >/dev/null

if [[ "${TEMP_DOCKERFILE_CREATED}" == "true" ]]; then
  rm -f ./Dockerfile
fi

echo "==> Deploying Cloud Run service (min=0, max=1)"
SET_SECRETS_ARGS=()
if [[ ${#SECRET_BINDINGS[@]} -gt 0 ]]; then
  SET_SECRETS_ARGS=(--set-secrets="$(IFS=,; echo "${SECRET_BINDINGS[*]}")")
fi

"${GCLOUD_BIN}" run deploy "${SERVICE_NAME}" \
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
  --set-env-vars="APP_ENV=prod,GCP_PROJECT_ID=${GCP_PROJECT_ID},GCP_REGION=${GCP_REGION},GCS_BUCKET=${GCS_BUCKET},CLOUD_TASKS_QUEUE=${QUEUE_NAME},CLOUD_TASKS_SERVICE_ACCOUNT=${TASKS_SA_EMAIL},API_SERVICE_ACCOUNT_EMAIL=${API_SA_EMAIL},FEATURE_VERTEX_AI=${FEATURE_VERTEX_AI},VERTEX_MODEL_DISPLAY_NAME=${VERTEX_MODEL_DISPLAY_NAME},TASKS_AUTH_REQUIRED=true,ALLOWED_ORIGINS=${ALLOWED_ORIGINS},FRONTEND_BASE_URL=${FRONTEND_BASE_URL}" \
  "${SET_SECRETS_ARGS[@]}" >/dev/null

SERVICE_URL="$("${GCLOUD_BIN}" run services describe "${SERVICE_NAME}" --region="${GCP_REGION}" --format='value(status.url)')"
TASKS_AUDIENCE="${SERVICE_URL}/tasks/handle"
DRIFT_URL="${SERVICE_URL}/api/v1/ml/drift-report"

echo "==> Updating Cloud Run runtime URLs"
"${GCLOUD_BIN}" run services update "${SERVICE_NAME}" \
  --region="${GCP_REGION}" \
  --update-env-vars="APP_BASE_URL=${SERVICE_URL},CLOUD_TASKS_AUDIENCE=${TASKS_AUDIENCE},SCHEDULER_TOKEN=${SCHEDULER_TOKEN}" >/dev/null

echo "==> Creating/updating Cloud Tasks queue"
if ! "${GCLOUD_BIN}" tasks queues describe "${QUEUE_NAME}" --location="${GCP_REGION}" >/dev/null 2>&1; then
  "${GCLOUD_BIN}" tasks queues create "${QUEUE_NAME}" \
    --location="${GCP_REGION}" \
    --max-concurrent-dispatches=1 \
    --max-dispatches-per-second=1 >/dev/null
else
  "${GCLOUD_BIN}" tasks queues update "${QUEUE_NAME}" \
    --location="${GCP_REGION}" \
    --max-concurrent-dispatches=1 \
    --max-dispatches-per-second=1 >/dev/null
fi

echo "==> Allowing Cloud Tasks principal to invoke /tasks/handle"
"${GCLOUD_BIN}" run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${GCP_REGION}" \
  --member="serviceAccount:${TASKS_SA_EMAIL}" \
  --role="roles/run.invoker" >/dev/null

echo "==> Creating/updating weekly Cloud Scheduler drift check"
HEADER_ARG=()
if [[ -n "${SCHEDULER_TOKEN}" ]]; then
  HEADER_ARG=(--headers="X-Scheduler-Token=${SCHEDULER_TOKEN}")
fi

if "${GCLOUD_BIN}" scheduler jobs describe "${SCHEDULER_JOB_NAME}" --location="${GCP_REGION}" >/dev/null 2>&1; then
  "${GCLOUD_BIN}" scheduler jobs delete "${SCHEDULER_JOB_NAME}" --location="${GCP_REGION}" --quiet >/dev/null
fi

"${GCLOUD_BIN}" scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
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
