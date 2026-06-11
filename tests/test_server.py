from fastapi.testclient import TestClient


def _client() -> TestClient:
    from server import app

    return TestClient(app)


def test_health_is_public():
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_protected_endpoint_rejects_missing_key():
    # /list-apps is an ADK endpoint; without the API key it must be blocked.
    resp = _client().get("/list-apps")
    assert resp.status_code == 401


def test_protected_endpoint_accepts_valid_key():
    resp = _client().get("/list-apps", headers={"X-API-Key": "test-secret-key"})
    assert resp.status_code == 200
