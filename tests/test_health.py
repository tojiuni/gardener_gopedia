def test_health(postgres_app_client):
    r = postgres_app_client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"
