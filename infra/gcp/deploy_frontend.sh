#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"

GCP_REGION="${GCP_REGION:-asia-southeast1}"
FRONTEND_SERVICE_NAME="${FRONTEND_SERVICE_NAME:-sg-route-opt-web}"
API_SERVICE_NAME="${API_SERVICE_NAME:-sg-route-opt-api}"
IMAGE_URI="${IMAGE_URI:-gcr.io/${GCP_PROJECT_ID}/${FRONTEND_SERVICE_NAME}:latest}"
GCLOUD_BIN="${GCLOUD_BIN:-gcloud}"

echo "==> Configuring project ${GCP_PROJECT_ID} (${GCP_REGION})"
"${GCLOUD_BIN}" config set project "${GCP_PROJECT_ID}" >/dev/null

if [[ -z "${API_URL:-}" ]]; then
  API_URL="$("${GCLOUD_BIN}" run services describe "${API_SERVICE_NAME}" --region="${GCP_REGION}" --format='value(status.url)')"
fi

if [[ -z "${API_URL}" ]]; then
  echo "ERROR: Could not determine API URL. Set API_URL explicitly."
  exit 1
fi

echo "==> Building frontend image with API base URL: ${API_URL}"
"${GCLOUD_BIN}" builds submit --config infra/gcp/cloudbuild.frontend.yaml --substitutions "_VITE_API_BASE_URL=${API_URL}" . >/dev/null

echo "==> Deploying frontend Cloud Run service: ${FRONTEND_SERVICE_NAME}"
"${GCLOUD_BIN}" run deploy "${FRONTEND_SERVICE_NAME}" \
  --image="${IMAGE_URI}" \
  --region="${GCP_REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --min-instances=0 \
  --max-instances=1 \
  --memory=512Mi \
  --cpu=1 >/dev/null

FRONTEND_URL="$("${GCLOUD_BIN}" run services describe "${FRONTEND_SERVICE_NAME}" --region="${GCP_REGION}" --format='value(status.url)')"

echo "==> Updating API CORS + frontend base URL"
"${GCLOUD_BIN}" run services update "${API_SERVICE_NAME}" \
  --region="${GCP_REGION}" \
  --update-env-vars="FRONTEND_BASE_URL=${FRONTEND_URL},ALLOWED_ORIGINS=${FRONTEND_URL}" >/dev/null

cat <<EOF
Frontend deployment complete.
Frontend URL: ${FRONTEND_URL}
API URL: ${API_URL}
EOF
