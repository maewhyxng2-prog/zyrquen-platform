"""FastAPI integration tests for Dataset Status API and Training Readiness/List/Gate APIs."""

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.database import Base, get_db
from apps.api.main import app
from apps.api.models import User
from apps.api.routers import training as training_router
from apps.api.security import get_current_user
from apps.api.training_models import TrainingRun
from apps.core.native.dataset import SCHEMA


def _build_valid_dataset(target_dir: Path, version: str = "0.1.0") -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    splits = {
        "train": json.dumps({"input": "alpha TR_E1", "target": "ok TR_E1"}) + "\n",
        "validation": json.dumps({"input": "beta VA_E2", "target": "ok VA_E2"}) + "\n",
        "test": json.dumps({"input": "gamma TE_E3", "target": "ok TE_E3"}) + "\n",
    }
    files = {}
    hashes = []
    for name, body in splits.items():
        data = body.encode("utf-8")
        (target_dir / f"{name}.jsonl").write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        files[f"{name}.jsonl"] = {"documents": 1, "sha256": sha}
        hashes.append(sha)
    content_sha = hashlib.sha256("".join(hashes).encode("utf-8")).hexdigest()
    manifest = {
        "schema": SCHEMA,
        "version": version,
        "content_sha256": content_sha,
        "sources": {"unit": {"license": "CC-BY-4.0", "sha256": content_sha}},
        "files": files,
    }
    (target_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return target_dir


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'datasets-training-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    user_id = uuid.uuid4()
    with TestingSession() as db:
        db.add(
            User(
                id=user_id,
                email="training-admin@example.com",
                password_hash="unused-in-this-test",
            )
        )
        db.commit()

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    test_user = User(
        id=user_id,
        email="training-admin@example.com",
        password_hash="unused-in-this-test",
    )
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    monkeypatch.setenv("ZYRQUEN_TRAINING_ADMIN_EMAILS", "training-admin@example.com")
    monkeypatch.delenv("ZYRQUEN_DATASET_DIR", raising=False)
    monkeypatch.delenv("ZYRQUEN_DATASET_ROOT", raising=False)
    monkeypatch.delenv("ZYRQUEN_TOKENIZER_PATH", raising=False)

    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        yield client, TestingSession, test_user, tmp_path

    app.dependency_overrides.clear()
    engine.dispose()


def test_dataset_status_requires_authentication(api_client):
    client, _, _, _ = api_client
    app.dependency_overrides.pop(get_current_user)
    resp = client.get("/v1/datasets/status")
    assert resp.status_code == 401


def test_dataset_status_unconfigured_vs_verified(api_client, monkeypatch):
    client, _, _, tmp_path = api_client
    unconfigured = client.get("/v1/datasets/status")
    assert unconfigured.status_code == 200
    assert unconfigured.json()["configured"] is False
    assert unconfigured.json()["status"] == "not_configured"

    unconfigured_ver = client.get("/v1/datasets/0.1.0/status")
    assert unconfigured_ver.status_code == 503

    root = tmp_path / "datasets"
    ds = _build_valid_dataset(root / "0.1.0", version="0.1.0")
    monkeypatch.setenv("ZYRQUEN_DATASET_DIR", str(ds))
    monkeypatch.setenv("ZYRQUEN_DATASET_ROOT", str(root))

    ready = client.get("/v1/datasets/status")
    assert ready.status_code == 200
    assert ready.json()["configured"] is True
    assert ready.json()["status"] == "ready"
    assert ready.json()["active_dataset"]["verified"] is True

    ver = client.get("/v1/datasets/0.1.0/status")
    assert ver.status_code == 200
    assert ver.json()["version"] == "0.1.0"
    assert ver.json()["verified"] is True

    missing = client.get("/v1/datasets/9.9.9/status")
    assert missing.status_code == 404

    invalid = client.get("/v1/datasets/v1..2/status")
    assert invalid.status_code == 422


def test_training_readiness_and_runs_list(api_client, monkeypatch):
    client, session_factory, user, tmp_path = api_client
    run_id = uuid.uuid4()
    with session_factory() as db:
        db.add(
            TrainingRun(
                id=run_id,
                owner_id=user.id,
                status="running",
                dataset_version="0.1.0",
                training_config={"max_steps": 10},
                model_config={"n_layers": 1},
            )
        )
        db.commit()

    readiness = client.get("/training/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["configured"] is False
    assert readiness.json()["tier2_approval_required"] is True
    assert readiness.json()["is_training_admin"] is True

    runs_resp = client.get("/training/runs")
    assert runs_resp.status_code == 200
    items = runs_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(run_id)
    assert items[0]["status"] == "failed"

    monkeypatch.setenv("ZYRQUEN_TRAINING_ADMIN_EMAILS", "other@example.com")
    forbidden = client.get("/training/runs")
    assert forbidden.status_code == 403


def test_training_start_enforces_tier2_approval_when_artifacts_configured(api_client, monkeypatch):
    client, _, _, tmp_path = api_client
    ds = _build_valid_dataset(tmp_path / "ds", version="0.1.0")
    tok = tmp_path / "tokenizer.json"
    tok.write_text('{"schema": "zyrquen.tokenizer.v2"}', encoding="utf-8")

    monkeypatch.setattr(training_router.jobs._orchestrator, "dataset_dir", ds)
    monkeypatch.setattr(training_router.jobs._orchestrator, "tokenizer_path", tok)

    missing_approval = client.post(
        "/training/runs",
        json={"dataset_version": "0.1.0"},
    )
    assert missing_approval.status_code == 403
    assert "approval_id is required" in missing_approval.json()["detail"]

    forged_approval = client.post(
        "/training/runs",
        json={"dataset_version": "0.1.0", "approval_id": "forged-id"},
    )
    assert forged_approval.status_code == 403
    assert "Tier-2 training approval rejected" in forged_approval.json()["detail"]



def test_training_readiness_runs_read_only_preflight(api_client, monkeypatch):
    client, _, _, tmp_path = api_client
    ds = _build_valid_dataset(tmp_path / "preflight-dataset", version="preflight-v1")
    tok = tmp_path / "native-tokenizer.json"
    tok.write_text('{"test": true}', encoding="utf-8")
    monkeypatch.setattr(training_router.jobs._orchestrator, "dataset_dir", ds)
    monkeypatch.setattr(training_router.jobs._orchestrator, "tokenizer_path", tok)

    calls = []
    def fake_prepare(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(training_router.jobs._orchestrator, "prepare", fake_prepare)
    response = client.get("/training/readiness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is True
    assert payload["dataset_integrity_verified"] is True
    assert payload["training_preflight_passed"] is True
    assert payload["dataset_version"] == "preflight-v1"
    assert payload["tier2_approval_required"] is True
    assert len(calls) == 1


def test_training_readiness_fails_closed_when_preflight_fails(api_client, monkeypatch):
    client, _, _, tmp_path = api_client
    ds = _build_valid_dataset(tmp_path / "preflight-invalid-dataset", version="preflight-v1")
    tok = tmp_path / "native-tokenizer-invalid.json"
    tok.write_text('{"test": true}', encoding="utf-8")
    monkeypatch.setattr(training_router.jobs._orchestrator, "dataset_dir", ds)
    monkeypatch.setattr(training_router.jobs._orchestrator, "tokenizer_path", tok)

    def fail_prepare(**kwargs):
        raise training_router.TrainingUnavailable("Native tokenizer failed validation.")

    monkeypatch.setattr(training_router.jobs._orchestrator, "prepare", fail_prepare)
    response = client.get("/training/readiness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is False
    assert payload["dataset_integrity_verified"] is False
    assert payload["training_preflight_passed"] is False
    assert payload["preflight_error"] == "Native tokenizer failed validation."
