def test_health_endpoint_returns_200_with_boolean_flag(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["env"] == "test"
    assert isinstance(body["ml_needs_retrain"], bool)
