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

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
