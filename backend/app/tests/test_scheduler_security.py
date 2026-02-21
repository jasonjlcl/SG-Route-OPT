from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import ml


def test_verify_scheduler_token_requires_config_outside_test(monkeypatch):
    monkeypatch.setattr(ml, "get_settings", lambda: SimpleNamespace(app_env="staging", scheduler_token=None))

    with pytest.raises(HTTPException) as exc:
        ml._verify_scheduler_token(x_scheduler_token=None)

    assert exc.value.status_code == 503


def test_verify_scheduler_token_rejects_invalid_token(monkeypatch):
    monkeypatch.setattr(ml, "get_settings", lambda: SimpleNamespace(app_env="staging", scheduler_token="secret-token"))

    with pytest.raises(HTTPException) as exc:
        ml._verify_scheduler_token(x_scheduler_token="wrong")

    assert exc.value.status_code == 401


def test_verify_scheduler_token_accepts_valid_token(monkeypatch):
    monkeypatch.setattr(ml, "get_settings", lambda: SimpleNamespace(app_env="staging", scheduler_token="secret-token"))
    ml._verify_scheduler_token(x_scheduler_token="secret-token")
