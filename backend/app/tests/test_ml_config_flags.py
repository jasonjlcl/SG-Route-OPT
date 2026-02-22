from types import SimpleNamespace

from app.api import ml


def test_ml_config_includes_vertex_batch_override_flag(client, monkeypatch):
    monkeypatch.setattr(
        ml,
        "get_settings",
        lambda: SimpleNamespace(feature_vertex_ai=True, feature_vertex_batch_override=False),
    )

    response = client.get("/api/v1/ml/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["feature_vertex_ai"] is True
    assert payload["feature_vertex_batch_override"] is False
