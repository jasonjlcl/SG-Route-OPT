from app.api import health as health_api


def test_health_endpoint_returns_200_with_boolean_flag(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["env"] == "test"
    assert isinstance(body["ml_needs_retrain"], bool)
    assert isinstance(body["feature_google_traffic"], bool)
    assert isinstance(body["feature_ml_uplift"], bool)
    assert isinstance(body["feature_eval_dashboard"], bool)


def test_health_live_endpoint_returns_200(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["env"] == "test"


def test_health_ready_endpoint_returns_200(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["checks"]["database"]["status"] == "ready"


def test_health_ready_returns_503_when_db_unready(client, monkeypatch):
    monkeypatch.setattr(health_api, "_check_database_ready", lambda: {"status": "unready", "detail": "db down"})
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["checks"]["database"]["status"] == "unready"
