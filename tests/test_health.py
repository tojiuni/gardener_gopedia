from fastapi.testclient import TestClient

from gardener_gopedia.db import init_db
from gardener_gopedia.main import app


def test_health():
    init_db()
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"
