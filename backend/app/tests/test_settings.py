from app.utils.settings import Settings


def test_default_cors_origins_allow_localhost_and_loopback():
    settings = Settings(_env_file=None)

    assert "http://localhost:5173" in settings.cors_origins
    assert "http://127.0.0.1:5173" in settings.cors_origins


def test_cors_origins_include_frontend_base_url():
    settings = Settings(
        _env_file=None,
        ALLOWED_ORIGINS="http://localhost:5173",
        FRONTEND_BASE_URL="http://127.0.0.1:5173/",
    )

    assert settings.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_cors_origins_expand_localhost_aliases_from_allowed_origins():
    settings = Settings(
        _env_file=None,
        ALLOWED_ORIGINS="http://localhost:5173",
        FRONTEND_BASE_URL="http://localhost:5173",
    )

    assert "http://localhost:5173" in settings.cors_origins
    assert "http://127.0.0.1:5173" in settings.cors_origins
