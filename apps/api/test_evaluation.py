import hashlib
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.database import Base, get_db
from apps.api.evaluation_models import EvaluationRun
from apps.api.main import app
from apps.api.models import User
from apps.api.security import get_current_user
from apps.core.native.dataset import PrepConfig, Source, prepare_dataset

client = TestClient(app, client=("127.0.0.1", 12345))


@pytest.fixture
def eval_client(tmp_path):
    db_engine = create_engine(
        f"sqlite:///{tmp_path / 'eval-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(db_engine)
    TestingSession = sessionmaker(
        bind=db_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    user_a = User(
        id=uuid.uuid4(),
        email="eval-user-a@example.com",
        password_hash="unused",
        role="user",
    )
    user_b = User(
        id=uuid.uuid4(),
        email="eval-user-b@example.com",
        password_hash="unused",
        role="user",
    )
    with TestingSession() as db:
        db.add(user_a)
        db.add(user_b)
        db.commit()

    active_user = {"user": user_a}

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: active_user["user"]
    with TestClient(app, client=("127.0.0.1", 12345)) as test_client:
        yield test_client, TestingSession, active_user, user_a, user_b
    app.dependency_overrides.clear()
    db_engine.dispose()


def _create_verified_dataset_and_checkpoint(tmp_path):
    src = tmp_path / "src.jsonl"
    docs = [
        {"text": f"ตัวอย่างข้อความที่ {i} and sample evaluation text number {i}"}
        for i in range(60)
    ]
    src.write_text(
        "\n".join(json.dumps(doc, ensure_ascii=False) for doc in docs),
        encoding="utf-8",
    )
    ds_root = tmp_path / "datasets"
    ds_dir = ds_root / "pilot-v1"
    report = prepare_dataset(
        [Source(str(src), "test-declared")],
        ds_dir,
        PrepConfig(val_fraction=0.2, test_fraction=0.2, version="0.1.0"),
    )
    checksum = report.manifest["content_sha256"]

    ckpt_dir = tmp_path / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    ckpt_file = ckpt_dir / "ckpt_00000010.pt"
    ckpt_bytes = b"verified-checkpoint-bytes"
    ckpt_file.write_bytes(ckpt_bytes)
    ckpt_sha = hashlib.sha256(ckpt_bytes).hexdigest()

    (ckpt_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "zyrquen.checkpoint-manifest.v1",
                "checkpoints": [
                    {
                        "step": 10,
                        "file": "ckpt_00000010.pt",
                        "size_bytes": len(ckpt_bytes),
                        "sha256": ckpt_sha,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (ckpt_dir / "version_manifest.json").write_text(
        json.dumps(
            {
                "schema": "zyrquen.model-version-manifest.v1",
                "versions": [
                    {
                        "model_version": "v0.1.0",
                        "parent_version": None,
                        "step": 10,
                        "checkpoint_file": "ckpt_00000010.pt",
                        "checkpoint_sha256": ckpt_sha,
                        "dataset_version": "0.1.0",
                        "dataset_content_hash": checksum,
                        "config_hash": "0" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return ds_root, ckpt_dir, checksum


def test_evaluation_unauthorized():
    response = client.post("/v1/evaluation/runs?model_version=v1")
    assert response.status_code == 401


def test_evaluation_rejects_missing_dataset_payload(eval_client):
    test_client, _, _, _, _ = eval_client
    response = test_client.post("/v1/evaluation/runs?model_version=v1")
    assert response.status_code == 422


def test_evaluation_reports_not_configured_when_env_unset(eval_client, monkeypatch):
    test_client, _, _, _, _ = eval_client
    monkeypatch.delenv("ZYRQUEN_EVALUATION_CHECKPOINT_DIR", raising=False)
    monkeypatch.delenv("ZYRQUEN_CHECKPOINT_DIR", raising=False)
    monkeypatch.delenv("ZYRQUEN_DATASET_ROOT", raising=False)

    response = test_client.post(
        "/v1/evaluation/runs",
        json={
            "model_version": "v0.1.0",
            "dataset_id": "pilot-v1",
            "dataset_checksum": "a" * 64,
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "not_configured"


def test_evaluation_rejects_missing_or_tampered_dataset_and_checkpoint(
    eval_client, tmp_path, monkeypatch
):
    test_client, _, _, _, _ = eval_client
    ds_root, ckpt_dir, checksum = _create_verified_dataset_and_checkpoint(tmp_path)
    monkeypatch.setenv("ZYRQUEN_EVALUATION_CHECKPOINT_DIR", str(ckpt_dir))
    monkeypatch.setenv("ZYRQUEN_DATASET_ROOT", str(ds_root))

    bad_checksum = test_client.post(
        "/v1/evaluation/runs",
        json={
            "model_version": "v0.1.0",
            "dataset_id": "pilot-v1",
            "dataset_checksum": "0" * 64,
        },
    )
    assert bad_checksum.status_code == 422

    missing_version = test_client.post(
        "/v1/evaluation/runs",
        json={
            "model_version": "v9.9.9",
            "dataset_id": "pilot-v1",
            "dataset_checksum": checksum,
        },
    )
    assert missing_version.status_code == 422

    valid_artifacts = test_client.post(
        "/v1/evaluation/runs",
        json={
            "model_version": "v0.1.0",
            "dataset_id": "pilot-v1",
            "dataset_checksum": checksum,
        },
    )
    assert valid_artifacts.status_code == 503
    assert valid_artifacts.json()["detail"]["status"] == "not_configured"


def test_list_evaluation_runs_enforces_ownership(eval_client):
    test_client, session_factory, active_user, user_a, user_b = eval_client
    with session_factory() as db:
        db.add(
            EvaluationRun(
                user_id=user_a.id,
                model_version="v0.1.0",
                dataset_id="pilot-v1",
                dataset_checksum="a" * 64,
                status="queued",
            )
        )
        db.add(
            EvaluationRun(
                user_id=user_b.id,
                model_version="v0.1.0",
                dataset_id="pilot-v1",
                dataset_checksum="b" * 64,
                status="queued",
            )
        )
        db.commit()

    res_a = test_client.get("/v1/evaluation/runs")
    assert res_a.status_code == 200
    assert res_a.json()["total"] == 1
    assert res_a.json()["items"][0]["user_id"] == str(user_a.id)

    active_user["user"] = user_b
    res_b = test_client.get("/v1/evaluation/runs")
    assert res_b.status_code == 200
    assert res_b.json()["total"] == 1
    assert res_b.json()["items"][0]["user_id"] == str(user_b.id)

