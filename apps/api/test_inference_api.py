"""Phase 5.6 / Phase 10 - Inference API.
Real-only, no mock engine.
Tiny native fixture is pipeline check. Not ZYRQUEN trained production weights.
"""
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from apps.api.database import Base, get_db
from apps.api.main import app
from apps.api.usage_models import UserQuotaPolicy
from apps.core.inference import NativeInferenceEngine
from apps.core.model_loader import NativeModelLoader
from apps.core.native.config import ZyrquenConfig
from apps.core.native.dataset import PrepConfig, Source, prepare_dataset
from apps.core.native.registry import ModelRegistry
from apps.core.native.tokenizer import BASE_VOCAB, N_SPECIAL, ZyrquenTokenizer
from apps.core.runtime import runtime
from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager


def _init_loader(loader):
    if hasattr(loader, "initialize"):
        return loader.initialize()
    if hasattr(loader, "load"):
        return loader.load()
    raise AssertionError("no init")


def _make_tiny_model_dir(
    path: Path,
    *,
    max_seq_len: int = 128,
    version: str = "ZYRQUEN-Native-0.1.0",
) -> Path:
    import torch
    from apps.core.native.model import ZyrquenModel

    path.mkdir(parents=True, exist_ok=True)
    src = path / "corpus.jsonl"
    docs = [
        {"text": f"hello world test zyrquen hi sample document {i} สวัสดี"}
        for i in range(40)
    ]
    src.write_text(
        "\n".join(json.dumps(doc, ensure_ascii=False) for doc in docs),
        encoding="utf-8",
    )
    ds_dir = path / "dataset"
    prepare_dataset(
        [Source(str(src), "test-fixture")],
        ds_dir,
        PrepConfig(val_fraction=0.1, test_fraction=0.1, version="0.1.0"),
    )

    tok = ZyrquenTokenizer.train(
        [doc["text"] for doc in docs],
        BASE_VOCAB + 32,
        version="0.1.0",
    )
    tok_path = path / "tokenizer.json"
    tok.save(tok_path)

    torch.manual_seed(7)
    cfg = ZyrquenConfig(
        vocab_size=tok.vocab_size,
        max_seq_len=max_seq_len,
        n_layers=2,
        n_heads=2,
        d_model=32,
        d_ff=64,
    )
    model = ZyrquenModel(cfg)
    with torch.no_grad():
        model.embed.weight[:N_SPECIAL].zero_()

    ckpt_dir = path / "checkpoints"
    CheckpointManager(ckpt_dir).save(
        0,
        {
            "model": model.state_dict(),
            "step": 0,
            "model_config": cfg.to_dict(),
            "tokenizer_sha256": tok.fingerprint(),
            "dataset_version": "0.1.0",
        },
    )

    reg_root = path / "registry"
    registry = ModelRegistry(reg_root)
    registry.register(version, ckpt_dir, tok_path, ds_dir, metrics={})
    registry.promote(version)
    return reg_root


@pytest.fixture()
def client(tmp_path, monkeypatch):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-56")
    loader = NativeModelLoader(model_path=str(mdir))
    _init_loader(loader)
    old_loader = runtime.loader
    old_engine = runtime.engine
    runtime.loader = loader
    old_initialized = runtime._initialized
    runtime.engine = NativeInferenceEngine(loader)
    runtime._initialized = True

    database_engine = create_engine(
        f"sqlite:///{tmp_path / 'inference-api.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(database_engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(database_engine)
    testing_session = sessionmaker(
        bind=database_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    def override_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setenv("JWT_SECRET_KEY", "inference-api-test-secret")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, client=("127.0.0.1", 12345)) as c:
        registered = c.post(
            "/auth/register",
            json={"email": "native-inference@example.com", "password": "StrongPass123456"},
        )
        assert registered.status_code == 200
        login = c.post(
            "/auth/login",
            json={"email": "native-inference@example.com", "password": "StrongPass123456"},
        )
        assert login.status_code == 200
        user_id = UUID(registered.json()["id"])
        with testing_session() as db:
            db.add(
                UserQuotaPolicy(
                    user_id=user_id,
                    max_requests=10,
                    max_input_tokens=10000,
                    max_output_tokens=10000,
                    max_total_tokens=20000,
                )
            )
            db.commit()
        c.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
        yield c
    app.dependency_overrides.clear()
    runtime.loader = old_loader
    runtime.engine = old_engine
    runtime._initialized = old_initialized
    database_engine.dispose()


def _parse_sse(text: str):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            continue
        try:
            out.append(json.loads(data))
        except Exception:
            pass
    return out


def _create_stream_conversation(client: TestClient, prompt: str) -> str:
    conversation = client.post(
        "/conversations",
        json={"title": prompt[:48]},
    )
    assert conversation.status_code == 201
    conversation_id = conversation.json()["id"]
    message = client.post(
        f"/conversations/{conversation_id}/messages",
        json={
            "id": str(uuid4()),
            "role": "user",
            "content": prompt,
        },
    )
    assert message.status_code == 201
    return conversation_id


def test_01_health(client):
    r = client.get("/v1/native-ai/health")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)
    assert data["runtime_status"] == "ready"
    assert data["native_model_loaded"] is True
    assert data["model_version"] == "ZYRQUEN-Native-0.1.0"


def test_02_infer(client):
    r = client.post(
        "/v1/native-ai/infer",
        json={
            "prompt": "hello world",
            "request_id": str(uuid4()),
            "max_tokens": 8,
            "temperature": 0.0,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    assert data["provider"] == "ZYRQUEN_NATIVE_CORE"
    assert data["model_version"] == "ZYRQUEN-Native-0.1.0"
    assert isinstance(data["result"], str)
    assert data["result"].strip() != ""


def test_03_stream(client):
    conversation_id = _create_stream_conversation(client, "hello world")
    r = client.post(
        "/v1/native-ai/infer/stream",
        json={
            "prompt": "hello world",
            "request_id": str(uuid4()),
            "conversation_id": conversation_id,
            "max_tokens": 8,
            "temperature": 0.7,
            "top_k": 5,
            "top_p": 0.9,
        },
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "[DONE]" in r.text
    chunks = _parse_sse(r.text)
    content = [c for c in chunks if not c.get("is_final")]
    assert len(content) >= 1
    assert len(content) <= 8
    assert chunks[-1].get("is_final") is True
    joined = "".join(c.get("text", "") for c in content)
    assert joined.strip() != ""


def test_04_validation_and_max_tokens(client):
    r = client.post(
        "/v1/native-ai/infer",
        json={
            "prompt": "hello world",
            "request_id": str(uuid4()),
            "max_tokens": 8,
            "temperature": 0.7,
            "top_p": 1.5,
        },
    )
    assert r.status_code == 422
    conversation_id = _create_stream_conversation(client, "hello world")
    r2 = client.post(
        "/v1/native-ai/infer/stream",
        json={
            "prompt": "hello world",
            "request_id": str(uuid4()),
            "conversation_id": conversation_id,
            "max_tokens": 4,
            "temperature": 0.0,
        },
    )
    assert r2.status_code == 200
    chunks = _parse_sse(r2.text)
    content = [c for c in chunks if not c.get("is_final")]
    assert len(content) <= 4
    assert chunks[-1].get("is_final") is True
