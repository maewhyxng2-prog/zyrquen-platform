"""Phase 5.1 - Native Inference.
Real-only, no mock.
Loader -> Engine -> model.generate()
Tiny fixture is only pipeline check.
Not ZYRQUEN production weights.
"""
import asyncio
from pathlib import Path

import pytest

try:
    from apps.core.inference import (
        InferenceContext,
        NativeInferenceEngine,
    )
except ImportError:
    from apps.api.routers.inference import (
        InferenceContext,
    )
    from apps.core.inference import (
        NativeInferenceEngine,
    )

try:
    from apps.core.inference import (
        InferenceError,
        ResourceLimitExceeded,
    )
except ImportError:
    from apps.core.errors import (
        InferenceError,
        ResourceLimitExceeded,
    )

from apps.core.model_loader import (
    ModelLoadError,
    ModelNotFoundError,
    NativeModelLoader,
)

def _init_loader(loader):
    if hasattr(loader, "initialize"):
        return loader.initialize()
    if hasattr(loader, "load"):
        return loader.load()
    raise AssertionError("no init")

def _make_engine(loader):
    try:
        return NativeInferenceEngine(loader)
    except TypeError:
        return NativeInferenceEngine(
            loader=loader,
        )

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

def test_01_missing_dir(tmp_path):
    bad = tmp_path / "does-not-exist"
    loader = NativeModelLoader(
        model_path=str(bad),
    )
    assert loader.is_ready() is False
    with pytest.raises(
        (ModelNotFoundError, ModelLoadError),
    ):
        _init_loader(loader)

def test_02_not_ready(tmp_path):
    bad = tmp_path / "does-not-exist"
    loader = NativeModelLoader(
        model_path=str(bad),
    )
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
    mdir = _make_tiny_model_dir(
        tmp_path / "tiny-native",
    )
    loader = NativeModelLoader(
        model_path=str(mdir),
    )
    _init_loader(loader)
    assert loader.is_ready() is True
    assert loader.model is not None
    assert loader.tokenizer is not None

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

def test_04_over_2048(tmp_path):
    mdir = _make_tiny_model_dir(
        tmp_path / "tiny-native",
    )
    loader = NativeModelLoader(
        model_path=str(mdir),
    )
    _init_loader(loader)
    engine = _make_engine(loader)
    long_prompt = "hello " * 2100
    ctx = InferenceContext.model_construct(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt=long_prompt,
        max_tokens=8,
        temperature=0.0,
    )
    with pytest.raises(ResourceLimitExceeded):
        asyncio.run(engine.execute(ctx))
