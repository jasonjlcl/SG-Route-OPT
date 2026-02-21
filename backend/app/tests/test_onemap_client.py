from __future__ import annotations

from types import SimpleNamespace

from app.services.onemap_client import OneMapClient
from app.utils.settings import get_settings


class DummyResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_onemap_client_mock_mode(monkeypatch):
    monkeypatch.delenv("ONEMAP_EMAIL", raising=False)
    monkeypatch.delenv("ONEMAP_PASSWORD", raising=False)
    get_settings.cache_clear()

    client = OneMapClient()
    assert client.mock_mode

    search = client.search("10 Bayfront Avenue")
    assert int(search["found"]) >= 1

    route = client.route(1.30, 103.80, 1.31, 103.81)
    assert route["distance_m"] > 0
    assert route["duration_s"] > 0


def test_onemap_client_refresh_on_401(monkeypatch):
    monkeypatch.setenv("ONEMAP_EMAIL", "user@example.com")
    monkeypatch.setenv("ONEMAP_PASSWORD", "secret")
    get_settings.cache_clear()

    client = OneMapClient()

    tokens = ["expired-token", "fresh-token"]
    calls = {"auth": 0, "request": 0}

    def fake_get_access_token(force_refresh: bool = False):
        if force_refresh:
            calls["auth"] += 1
            return tokens[1]
        return tokens[0]

    def fake_request(method, url, params=None, headers=None):
        calls["request"] += 1
        if calls["request"] == 1:
            return DummyResponse(401, {})
        return DummyResponse(200, {"found": 1, "results": []})

    monkeypatch.setattr(client, "get_access_token", fake_get_access_token)
    monkeypatch.setattr(client, "http", SimpleNamespace(request=fake_request))

    data = client._request_with_retries("GET", "https://example.com")
    assert data["found"] == 1
    assert calls["auth"] == 1
    assert calls["request"] == 2


def test_onemap_client_route_fallback_on_failure(monkeypatch):
    monkeypatch.setenv("ONEMAP_EMAIL", "user@example.com")
    monkeypatch.setenv("ONEMAP_PASSWORD", "secret")
    get_settings.cache_clear()

    client = OneMapClient()

    def fail_request(*args, **kwargs):
        raise RuntimeError("routing unavailable")

    monkeypatch.setattr(client, "_request_with_retries", fail_request)

    route = client.route(1.3000, 103.8000, 1.3200, 103.8200)
    assert route["distance_m"] > 0
    assert route["duration_s"] > 0


def test_onemap_search_does_not_mock_in_prod(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ONEMAP_EMAIL", "user@example.com")
    monkeypatch.setenv("ONEMAP_PASSWORD", "secret")
    get_settings.cache_clear()

    client = OneMapClient()

    def fail_request(*args, **kwargs):
        raise RuntimeError("search unavailable")

    monkeypatch.setattr(client, "_request_with_retries", fail_request)

    import pytest

    with pytest.raises(RuntimeError):
        client.search("10 Bayfront Avenue")


def test_onemap_reverse_geocode_parses_payload(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ONEMAP_EMAIL", "user@example.com")
    monkeypatch.setenv("ONEMAP_PASSWORD", "secret")
    get_settings.cache_clear()

    client = OneMapClient()
    monkeypatch.setattr(
        client,
        "_request_with_retries",
        lambda *args, **kwargs: {
            "GeocodeInfo": [
                {
                    "BLK_NO": "1",
                    "ROAD": "Raffles Place",
                    "POSTALCODE": "048616",
                }
            ]
        },
    )

    result = client.reverse_geocode(1.284, 103.851)
    assert result["postal_code"] == "048616"
    assert "Raffles Place" in (result["address"] or "")
