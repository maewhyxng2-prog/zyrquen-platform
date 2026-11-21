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


def test_unhandled_exception_returns_500_json_without_name_error():
    from fastapi import FastAPI
    from apps.api.operations import install_exception_logging

    probe_app = FastAPI()
    install_exception_logging(probe_app)

    @probe_app.get("/_probe_error")
    async def _probe_error():
        raise RuntimeError("boom")

    probe_client = TestClient(probe_app, raise_server_exceptions=False)
    response = probe_client.get("/_probe_error")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
