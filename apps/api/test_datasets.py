import hashlib
import json

from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.routers.training import get_current_user


def test_dataset_status_requires_authentication():
    app.dependency_overrides.pop(get_current_user, None)
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        response = client.get("/v1/datasets/status")
    assert response.status_code == 401


def test_dataset_status_reports_unconfigured(monkeypatch):
    monkeypatch.delenv("ZYRQUEN_DATASET_DIR", raising=False)
    app.dependency_overrides[get_current_user] = lambda: object()
    try:
        with TestClient(app, client=("127.0.0.1", 12345)) as client:
            response = client.get("/v1/datasets/status")
        assert response.status_code == 200
        assert response.json()["status"] == "not_configured"
        assert response.json()["valid"] is False
    finally:
        app.dependency_overrides.clear()


def test_dataset_status_verifies_manifest_and_splits(tmp_path, monkeypatch):
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    names = ("train", "validation", "test")
    hashes = {}
    for name in names:
        path = dataset_dir / f"{name}.jsonl"
        path.write_text("", encoding="utf-8")
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    content_hash = hashlib.sha256("".join(hashes[f"{name}.jsonl"] for name in names).encode()).hexdigest()
    manifest = {
        "schema": "zyrquen.dataset-manifest.v1",
        "version": "test-1",
        "content_sha256": content_hash,
        "files": {f"{name}.jsonl": {"documents": 0, "sha256": hashes[f"{name}.jsonl"]} for name in names},
    }
    (dataset_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("ZYRQUEN_DATASET_DIR", str(dataset_dir))
    app.dependency_overrides[get_current_user] = lambda: object()
    try:
        with TestClient(app, client=("127.0.0.1", 12345)) as client:
            response = client.get("/v1/datasets/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["valid"] is True
        assert payload["version"] == "test-1"
        assert payload["splits"]["train"]["documents"] == 0
    finally:
        app.dependency_overrides.clear()
