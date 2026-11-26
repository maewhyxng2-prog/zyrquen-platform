"""Phase 5.1 / Phase 10 - Native Inference.
Real-only, no mock.
Loader -> Registry Verification -> ZyrquenModel / ZyrquenTokenizer.
Tiny fixture is only pipeline check. Not ZYRQUEN trained production weights.
"""
import asyncio
import json
from pathlib import Path

import pytest

from apps.core.context import InferenceContext
from apps.core.exceptions import InferenceError, ResourceLimitExceeded
from apps.core.inference import NativeInferenceEngine
from apps.core.model_loader import (
    ModelLoadError,
    ModelNotFoundError,
    NativeModelLoader,
)
from apps.core.native.config import ZyrquenConfig
from apps.core.native.dataset import PrepConfig, Source, prepare_dataset
from apps.core.native.registry import ModelRegistry
from apps.core.native.tokenizer import BASE_VOCAB, N_SPECIAL, ZyrquenTokenizer
from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager


def _init_loader(loader):
    if hasattr(loader, "initialize"):
        return loader.initialize()
    if hasattr(loader, "load"):
        return loader.load()
    raise AssertionError("no init")


def _make_engine(loader):
    return NativeInferenceEngine(loader)


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


def test_01_missing_dir(tmp_path):
    bad = tmp_path / "does-not-exist"
    loader = NativeModelLoader(model_path=str(bad))
    assert loader.is_ready() is False
    with pytest.raises((ModelNotFoundError, ModelLoadError)):
        _init_loader(loader)


def test_02_not_ready(tmp_path):
    bad = tmp_path / "does-not-exist"
    loader = NativeModelLoader(model_path=str(bad))
    engine = _make_engine(loader)
    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt="hello world",
        max_tokens=8,
        temperature=0.0,
    )
    with pytest.raises(InferenceError):
        asyncio.run(engine.execute(ctx))


def test_03_real_generate(tmp_path):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-native")
    loader = NativeModelLoader(model_path=str(mdir))
    _init_loader(loader)
    assert loader.is_ready() is True
    assert loader.model is not None
    assert loader.tokenizer is not None
    assert loader.model_version == "ZYRQUEN-Native-0.1.0"

    engine = _make_engine(loader)
    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt="hello world",
        max_tokens=8,
        temperature=0.0,
    )
    result = asyncio.run(engine.execute(ctx))
    assert isinstance(result, str)
    assert result.strip() != ""
    assert "mock" not in result.lower()


def test_04_over_max_seq_len(tmp_path):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-native", max_seq_len=128)
    loader = NativeModelLoader(model_path=str(mdir))
    _init_loader(loader)
    engine = _make_engine(loader)
    long_prompt = "hello " * 200
    ctx = InferenceContext.model_construct(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt=long_prompt,
        max_tokens=8,
        temperature=0.0,
    )
    with pytest.raises(ResourceLimitExceeded):
        asyncio.run(engine.execute(ctx))
