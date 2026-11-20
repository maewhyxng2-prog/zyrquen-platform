"""Phase 5.6 - Inference API.
Real-only, no mock engine.
Tiny fixture is pipeline check.
Not production weights.
"""
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.security import get_current_user
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
def client(tmp_path):
    mdir = _make_tiny_model_dir(
        tmp_path / "tiny-56",
    )
    loader = NativeModelLoader(
        model_path=str(mdir),
    )
    _init_loader(loader)
    old_loader = runtime.loader
    old_engine = runtime.engine
    runtime.loader = loader
    old_initialized = runtime._initialized
    runtime.engine = NativeInferenceEngine(loader)
    runtime._initialized = True
    fake = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    app.dependency_overrides[get_current_user] = lambda: fake
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()
    runtime.loader = old_loader
    runtime.engine = old_engine
    runtime._initialized = old_initialized

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
    r = client.post(
        "/v1/native-ai/infer/stream",
        json={
            "prompt": "hello world",
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
            "max_tokens": 8,
            "temperature": 0.7,
            "top_p": 1.5,
        },
    )
    assert r.status_code == 422
    r2 = client.post(
        "/v1/native-ai/infer/stream",
        json={
            "prompt": "hello world",
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
