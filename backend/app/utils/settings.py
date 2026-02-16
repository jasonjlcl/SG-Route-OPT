from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = Field(default="dev", alias="APP_ENV")
    database_url: str = Field(default="sqlite:///./app.db", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    onemap_email: str | None = Field(default=None, alias="ONEMAP_EMAIL")
    onemap_password: str | None = Field(default=None, alias="ONEMAP_PASSWORD")

    max_upload_mb: int = Field(default=10, alias="MAX_UPLOAD_MB")
    allowed_origins: str = Field(default="http://localhost:5173", alias="ALLOWED_ORIGINS")

    onemap_auth_url: str = Field(default="https://www.onemap.gov.sg/api/auth/post/getToken", alias="ONEMAP_AUTH_URL")
    onemap_search_url: str = Field(default="https://www.onemap.gov.sg/api/common/elastic/search", alias="ONEMAP_SEARCH_URL")
    onemap_routing_url: str = Field(default="https://www.onemap.gov.sg/api/public/routingsvc/route", alias="ONEMAP_ROUTING_URL")
    app_base_url: str = Field(default="http://localhost:8000", alias="APP_BASE_URL")
    frontend_base_url: str = Field(default="http://localhost:5173", alias="FRONTEND_BASE_URL")
    jobs_force_inline: bool = Field(default=False, alias="JOBS_FORCE_INLINE")

    ml_drift_threshold: float = Field(default=0.2, alias="ML_DRIFT_THRESHOLD")
    ml_retrain_min_rows: int = Field(default=200, alias="ML_RETRAIN_MIN_ROWS")
    ml_canary_seed: int = Field(default=42, alias="ML_CANARY_SEED")

    gcp_project_id: str | None = Field(default=None, alias="GCP_PROJECT_ID")
    gcp_region: str = Field(default="asia-southeast1", alias="GCP_REGION")
    gcs_bucket: str | None = Field(default=None, alias="GCS_BUCKET")
    maps_static_api_key: str | None = Field(default=None, alias="MAPS_STATIC_API_KEY")

    feature_vertex_ai: bool = Field(default=False, alias="FEATURE_VERTEX_AI")
    vertex_model_display_name: str = Field(default="route-time-regressor", alias="VERTEX_MODEL_DISPLAY_NAME")

    cloud_tasks_queue: str = Field(default="route-jobs", alias="CLOUD_TASKS_QUEUE")
    cloud_tasks_service_account: str | None = Field(default=None, alias="CLOUD_TASKS_SERVICE_ACCOUNT")
    tasks_auth_required: bool = Field(default=True, alias="TASKS_AUTH_REQUIRED")
    cloud_tasks_audience: str | None = Field(default=None, alias="CLOUD_TASKS_AUDIENCE")
    api_service_account_email: str | None = Field(default=None, alias="API_SERVICE_ACCOUNT_EMAIL")

    scheduler_token: str | None = Field(default=None, alias="SCHEDULER_TOKEN")
    signed_url_ttl_seconds: int = Field(default=3600, alias="SIGNED_URL_TTL_SECONDS")

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
