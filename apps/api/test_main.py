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
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
