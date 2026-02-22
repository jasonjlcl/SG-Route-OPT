from functools import lru_cache

from pydantic import Field, field_validator, model_validator
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
    onemap_reverse_geocode_url: str = Field(
        default="https://www.onemap.gov.sg/api/public/revgeocode",
        alias="ONEMAP_REVERSE_GEOCODE_URL",
    )
    app_base_url: str = Field(default="http://localhost:8000", alias="APP_BASE_URL")
    frontend_base_url: str = Field(default="http://localhost:5173", alias="FRONTEND_BASE_URL")
    jobs_force_inline: bool = Field(default=False, alias="JOBS_FORCE_INLINE")
    optimize_max_stops: int = Field(default=80, ge=1, alias="OPTIMIZE_MAX_STOPS")
    optimize_max_matrix_elements: int = Field(default=6500, ge=1, alias="OPTIMIZE_MAX_MATRIX_ELEMENTS")

    ml_drift_threshold: float = Field(default=0.2, alias="ML_DRIFT_THRESHOLD")
    ml_retrain_min_rows: int = Field(default=200, alias="ML_RETRAIN_MIN_ROWS")
    ml_canary_seed: int = Field(default=42, alias="ML_CANARY_SEED")

    gcp_project_id: str | None = Field(default=None, alias="GCP_PROJECT_ID")
    gcp_region: str = Field(default="asia-southeast1", alias="GCP_REGION")
    gcs_bucket: str | None = Field(default=None, alias="GCS_BUCKET")
    maps_static_api_key: str | None = Field(default=None, alias="MAPS_STATIC_API_KEY")

    feature_vertex_ai: bool = Field(default=False, alias="FEATURE_VERTEX_AI")
    feature_vertex_batch_override: bool = Field(default=True, alias="FEATURE_VERTEX_BATCH_OVERRIDE")
    vertex_model_display_name: str = Field(default="route-time-regressor", alias="VERTEX_MODEL_DISPLAY_NAME")
    vertex_batch_machine_type: str = Field(default="n1-standard-4", alias="VERTEX_BATCH_MACHINE_TYPE")
    vertex_batch_starting_replica_count: int = Field(default=1, ge=1, alias="VERTEX_BATCH_STARTING_REPLICA_COUNT")
    vertex_batch_max_replica_count: int = Field(default=1, ge=1, alias="VERTEX_BATCH_MAX_REPLICA_COUNT")
    vertex_batch_timeout_seconds: int = Field(default=300, ge=10, alias="VERTEX_BATCH_TIMEOUT_SECONDS")
    vertex_batch_poll_interval_seconds: int = Field(default=5, ge=1, alias="VERTEX_BATCH_POLL_INTERVAL_SECONDS")
    vertex_batch_output_wait_seconds: int = Field(default=30, ge=0, alias="VERTEX_BATCH_OUTPUT_WAIT_SECONDS")
    feature_google_traffic: bool = Field(default=False, alias="FEATURE_GOOGLE_TRAFFIC")
    feature_ml_uplift: bool = Field(default=False, alias="FEATURE_ML_UPLIFT")
    feature_eval_dashboard: bool = Field(default=False, alias="FEATURE_EVAL_DASHBOARD")
    google_routes_api_key: str | None = Field(default=None, alias="GOOGLE_ROUTES_API_KEY")
    google_maps_api_key: str | None = Field(default=None, alias="GOOGLE_MAPS_API_KEY")
    google_routes_region: str = Field(default="asia-southeast1", alias="GOOGLE_ROUTES_REGION")
    google_routing_preference: str = Field(default="TRAFFIC_AWARE", alias="GOOGLE_ROUTING_PREFERENCE")
    google_matrix_max_elements: int = Field(default=25, alias="GOOGLE_MATRIX_MAX_ELEMENTS")
    google_cache_ttl_seconds: int = Field(default=600, alias="GOOGLE_CACHE_TTL_SECONDS")
    google_traffic_mode: str = Field(default="TRAFFIC_AWARE", alias="GOOGLE_TRAFFIC_MODE")
    google_max_elements_per_job: int = Field(default=2500, alias="GOOGLE_MAX_ELEMENTS_PER_JOB")
    google_timeout_seconds: int = Field(default=20, alias="GOOGLE_TIMEOUT_SECONDS")
    google_rate_limit_qps: float = Field(default=5.0, alias="GOOGLE_RATE_LIMIT_QPS")

    cloud_tasks_queue: str = Field(default="route-jobs", alias="CLOUD_TASKS_QUEUE")
    cloud_tasks_service_account: str | None = Field(default=None, alias="CLOUD_TASKS_SERVICE_ACCOUNT")
    tasks_auth_required: bool = Field(default=True, alias="TASKS_AUTH_REQUIRED")
    cloud_tasks_audience: str | None = Field(default=None, alias="CLOUD_TASKS_AUDIENCE")
    api_service_account_email: str | None = Field(default=None, alias="API_SERVICE_ACCOUNT_EMAIL")
    pipeline_step_lease_seconds: int = Field(default=900, alias="PIPELINE_STEP_LEASE_SECONDS")
    pipeline_retry_drill_step: str | None = Field(default=None, alias="PIPELINE_RETRY_DRILL_STEP")
    pipeline_retry_drill_delay_seconds: int = Field(default=0, alias="PIPELINE_RETRY_DRILL_DELAY_SECONDS")

    scheduler_token: str | None = Field(default=None, alias="SCHEDULER_TOKEN")
    signed_url_ttl_seconds: int = Field(default=3600, alias="SIGNED_URL_TTL_SECONDS")
    optimize_latency_warn_seconds: int = Field(default=1200, ge=60, alias="OPTIMIZE_LATENCY_WARN_SECONDS")

    @field_validator(
        "onemap_email",
        "onemap_password",
        "maps_static_api_key",
        "google_routes_api_key",
        "google_maps_api_key",
        "cloud_tasks_service_account",
        "cloud_tasks_audience",
        "api_service_account_email",
        "scheduler_token",
        mode="before",
    )
    @classmethod
    def _normalize_optional_secret(cls, value: object) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator(
        "database_url",
        "app_base_url",
        "frontend_base_url",
        "gcp_project_id",
        "gcp_region",
        "gcs_bucket",
        "vertex_batch_machine_type",
        "cloud_tasks_queue",
        mode="before",
    )
    @classmethod
    def _normalize_required_strings(cls, value: object) -> str:
        return str(value or "").strip()

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def resolved_google_routes_api_key(self) -> str | None:
        key = self.google_routes_api_key or self.google_maps_api_key
        if key is None:
            return None
        cleaned = str(key).strip()
        return cleaned or None

    @property
    def resolved_google_routing_preference(self) -> str:
        return str(self.google_routing_preference or self.google_traffic_mode or "TRAFFIC_AWARE").upper()

    @property
    def resolved_google_matrix_max_elements(self) -> int:
        return int(self.google_matrix_max_elements or self.google_max_elements_per_job or 25)

    @property
    def is_cloud_mode(self) -> bool:
        return str(self.app_env or "").strip().lower() in {"prod", "production", "staging"}

    @property
    def is_production_mode(self) -> bool:
        return str(self.app_env or "").strip().lower() in {"prod", "production"}

    @model_validator(mode="after")
    def _validate_required_production_settings(self) -> "Settings":
        if self.vertex_batch_max_replica_count < self.vertex_batch_starting_replica_count:
            raise ValueError("VERTEX_BATCH_MAX_REPLICA_COUNT must be >= VERTEX_BATCH_STARTING_REPLICA_COUNT.")

        if not self.is_production_mode:
            return self

        missing: list[str] = []
        if not self.database_url:
            missing.append("DATABASE_URL")
        elif self.database_url.startswith("sqlite"):
            raise ValueError("DATABASE_URL must not use sqlite in production.")

        if not self.gcp_project_id:
            missing.append("GCP_PROJECT_ID")
        if not self.gcs_bucket:
            missing.append("GCS_BUCKET")
        if not self.cloud_tasks_queue:
            missing.append("CLOUD_TASKS_QUEUE")
        if not self.cloud_tasks_service_account:
            missing.append("CLOUD_TASKS_SERVICE_ACCOUNT")
        if not self.scheduler_token:
            missing.append("SCHEDULER_TOKEN")
        if not self.onemap_email:
            missing.append("ONEMAP_EMAIL")
        if not self.onemap_password:
            missing.append("ONEMAP_PASSWORD")

        if missing:
            joined = ", ".join(sorted(set(missing)))
            raise ValueError(f"Missing required production settings: {joined}")

        if not self.tasks_auth_required:
            raise ValueError("TASKS_AUTH_REQUIRED must be true in production.")
        if self.feature_google_traffic and not self.resolved_google_routes_api_key:
            raise ValueError("GOOGLE_ROUTES_API_KEY (or GOOGLE_MAPS_API_KEY) is required when FEATURE_GOOGLE_TRAFFIC=true.")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
