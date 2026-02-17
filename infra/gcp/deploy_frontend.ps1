param(
    [string]$GcpProjectId = $env:GCP_PROJECT_ID,
    [string]$GcpRegion = $(if ($env:GCP_REGION) { $env:GCP_REGION } else { "asia-southeast1" }),
    [string]$FrontendServiceName = $(if ($env:FRONTEND_SERVICE_NAME) { $env:FRONTEND_SERVICE_NAME } else { "sg-route-opt-web" }),
    [string]$ApiServiceName = $(if ($env:API_SERVICE_NAME) { $env:API_SERVICE_NAME } else { "sg-route-opt-api" }),
    [string]$ApiUrl = $env:API_URL
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($GcpProjectId)) {
    throw "Set GCP_PROJECT_ID first."
}

Write-Host "==> Configuring project $GcpProjectId ($GcpRegion)"
gcloud config set project $GcpProjectId | Out-Null

if ([string]::IsNullOrWhiteSpace($ApiUrl)) {
    $ApiUrl = gcloud run services describe $ApiServiceName --region $GcpRegion --format "value(status.url)"
}
if ([string]::IsNullOrWhiteSpace($ApiUrl)) {
    throw "Could not determine API URL. Set API_URL and rerun."
}

Write-Host "==> Building frontend image with API base URL: $ApiUrl"
gcloud builds submit --config infra/gcp/cloudbuild.frontend.yaml --substitutions "_VITE_API_BASE_URL=$ApiUrl" . | Out-Null

$ImageUri = "gcr.io/$GcpProjectId/$FrontendServiceName`:latest"

Write-Host "==> Deploying frontend Cloud Run service: $FrontendServiceName"
gcloud run deploy $FrontendServiceName `
    --image $ImageUri `
    --region $GcpRegion `
    --platform managed `
    --allow-unauthenticated `
    --port 8080 `
    --min-instances 0 `
    --max-instances 1 `
    --memory 512Mi `
    --cpu 1 | Out-Null

$FrontendUrl = gcloud run services describe $FrontendServiceName --region $GcpRegion --format "value(status.url)"

Write-Host "==> Updating API CORS + frontend base URL"
gcloud run services update $ApiServiceName `
    --region $GcpRegion `
    --update-env-vars "FRONTEND_BASE_URL=$FrontendUrl,ALLOWED_ORIGINS=$FrontendUrl" | Out-Null

Write-Host "Frontend deployment complete."
Write-Host "Frontend URL: $FrontendUrl"
Write-Host "API URL: $ApiUrl"
