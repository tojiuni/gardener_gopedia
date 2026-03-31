import pytest


def test_health(postgres_app_client):
    r = postgres_app_client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


@pytest.mark.integration
def test_gopedia_health(gopedia_client):
    r = gopedia_client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


@pytest.mark.integration
def test_gardener_health(gardener_client):
    r = gardener_client.get("/health")
    if r.status_code == 404:
        r = gardener_client.get("/docs")
    assert r.status_code == 200
