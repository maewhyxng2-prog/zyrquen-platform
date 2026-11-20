"""Phase 5.6 - Inference API.
Real-only, no mock engine.
Tiny fixture is pipeline check.
Not production weights.
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
from apps.core.runtime import runtime

def _init_loader(loader):
    if hasattr(loader, "initialize"):
        return loader.initialize()
    if hasattr(loader, "load"):
        return loader.load()
    raise AssertionError("no init")

def _make_tiny_model_dir(path: Path) -> Path:
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import GPT2Config
    from transformers import GPT2LMHeadModel
    from transformers import PreTrainedTokenizerFast

    path.mkdir(parents=True, exist_ok=True)
    base = [
        "<|endoftext|>",
        "[PAD]",
        "[UNK]",
        "hello",
        "world",
        "test",
        "zyrquen",
        "hi",
    ]
    vocab = {}
    for i, tok in enumerate(base):
        vocab[tok] = i
    idx = len(base)
    while len(vocab) < 64:
        tok = f"tok{idx}"
        vocab[tok] = idx
        idx += 1

    wl = WordLevel(
        vocab=vocab,
        unk_token="[UNK]",
    )
    tok_obj = Tokenizer(wl)
    tok_obj.pre_tokenizer = Whitespace()
    fast = PreTrainedTokenizerFast(
        tokenizer_object=tok_obj,
        unk_token="[UNK]",
        pad_token="[PAD]",
        eos_token="<|endoftext|>",
        bos_token="<|endoftext|>",
    )
    fast.save_pretrained(str(path))

    cfg = GPT2Config(
        vocab_size=len(vocab),
        n_layer=2,
        n_head=2,
        n_embd=32,
        n_positions=128,
        n_ctx=128,
        pad_token_id=vocab["[PAD]"],
        eos_token_id=vocab["<|endoftext|>"],
        bos_token_id=vocab["<|endoftext|>"],
    )
    model = GPT2LMHeadModel(cfg)
    model.save_pretrained(str(path))
    return path

@pytest.fixture()
def client(tmp_path, monkeypatch):
    mdir = _make_tiny_model_dir(
        tmp_path / "tiny-56",
    )
    loader = NativeModelLoader(
        model_path=str(mdir),
    )
    _init_loader(loader)
    loader.tokenizer.eos_token_id = None
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
        c.headers.update(
            {"Authorization": f"Bearer {login.json()['access_token']}"}
        )
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
    assert (
        "native_model_loaded" in data
        or "runtime_status" in data
        or "status" in data
    )

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
    content = [
        c for c in chunks if not c.get("is_final")
    ]
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
    content = [
        c for c in chunks if not c.get("is_final")
    ]
    assert len(content) <= 4
    assert chunks[-1].get("is_final") is True
