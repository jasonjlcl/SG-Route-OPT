import pytest
from pydantic import ValidationError

from app.utils.settings import Settings


def _base_prod_settings() -> dict[str, str]:
    return {
        "APP_ENV": "prod",
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/routeopt",
        "ONEMAP_EMAIL": "ops@example.com",
        "ONEMAP_PASSWORD": "secret-pass",
        "GCP_PROJECT_ID": "demo-project",
        "GCS_BUCKET": "gs://route_app",
        "CLOUD_TASKS_QUEUE": "route-jobs",
        "CLOUD_TASKS_SERVICE_ACCOUNT": "tasks@example.iam.gserviceaccount.com",
        "SCHEDULER_TOKEN": "scheduler-secret",
        "TASKS_AUTH_REQUIRED": "true",
    }


def _load_with_env(monkeypatch, values: dict[str, str]) -> Settings:
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return Settings()


def test_prod_settings_require_non_empty_scheduler_token(monkeypatch):
    data = _base_prod_settings()
    data["SCHEDULER_TOKEN"] = "   "
    with pytest.raises(ValidationError):
        _load_with_env(monkeypatch, data)


def test_prod_settings_reject_sqlite_database(monkeypatch):
    data = _base_prod_settings()
    data["DATABASE_URL"] = "sqlite:///./app.db"
    with pytest.raises(ValidationError):
        _load_with_env(monkeypatch, data)


def test_settings_normalize_secret_whitespace(monkeypatch):
    settings = _load_with_env(
        monkeypatch,
        {
            "APP_ENV": "dev",
            "SCHEDULER_TOKEN": "  token-123  ",
            "GOOGLE_ROUTES_API_KEY": "   ",
        },
    )
    assert settings.scheduler_token == "token-123"
    assert settings.google_routes_api_key is None
