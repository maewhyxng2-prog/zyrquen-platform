from fastapi.testclient import TestClient
from main import app

client = TestClient(app, client=("127.0.0.1", 12345))


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["platform"] == "ZYRQUEN Ω∞"
    assert response.json()["mode"] == "online"


def test_health():
    response = client.get("/health")
    assert response.status_code in (200, 503)
    assert response.json()["status"] in ("healthy", "degraded", "unavailable")
    assert "database" in response.json()
    assert "native_ai" in response.json()


def test_liveness_does_not_probe_dependencies():
    response = client.get("/livez")
    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "zyrquen-api",
    }


def test_readiness_reports_real_dependency_states():
    response = client.get("/readyz")
    assert response.status_code in (200, 503)
    body = response.json()
    assert body["status"] in ("healthy", "degraded", "unavailable")
    assert body["database"]["status"] in ("healthy", "unavailable")
    assert body["native_ai"]["runtime_status"] in (
        "ready",
        "degraded",
        "not_configured",
    )


def test_request_observability_headers():
    response = client.get("/livez", headers={"X-Correlation-ID": "test-correlation"})
    assert response.headers["x-correlation-id"] == "test-correlation"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
