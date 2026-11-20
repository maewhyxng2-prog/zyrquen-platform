"""Phase 5.2 - Token Generation.
Real-only, no mock.
Tiny fixture is pipeline check.
Not production weights.
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

from apps.core.model_loader import (
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

def _count_tokens(loader, text):
    tok = loader.tokenizer
    ids = tok.encode(
        text,
        add_special_tokens=False,
    )
    return len(ids)

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

def _run(loader, prompt, max_t, temp):
    engine = _make_engine(loader)
    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt=prompt,
        max_tokens=max_t,
        temperature=temp,
    )
    return asyncio.run(engine.execute(ctx))

def test_01_max_tokens_respected(tmp_path):
    mdir = _make_tiny_model_dir(
        tmp_path / "tiny-52",
    )
    loader = NativeModelLoader(
        model_path=str(mdir),
    )
    _init_loader(loader)
    out = _run(loader, "hello world", 4, 0.0)
    assert isinstance(out, str)
    assert out.strip() != ""
    n = _count_tokens(loader, out)
    assert 0 < n <= 4

def test_02_continuous_generation(tmp_path):
    mdir = _make_tiny_model_dir(
        tmp_path / "tiny-52",
    )
    loader = NativeModelLoader(
        model_path=str(mdir),
    )
    _init_loader(loader)
    short = _run(loader, "hello world", 2, 0.0)
    long = _run(loader, "hello world", 12, 0.0)
    ns = _count_tokens(loader, short)
    nl = _count_tokens(loader, long)
    assert ns <= 2
    assert nl <= 12
    assert nl >= ns

def test_03_greedy_deterministic(tmp_path):
    mdir = _make_tiny_model_dir(
        tmp_path / "tiny-52",
    )
    loader = NativeModelLoader(
        model_path=str(mdir),
    )
    _init_loader(loader)
    a = _run(loader, "hello world", 8, 0.0)
    b = _run(loader, "hello world", 8, 0.0)
    assert a == b

def test_04_sampling_and_eos(tmp_path):
    mdir = _make_tiny_model_dir(
        tmp_path / "tiny-52",
    )
    loader = NativeModelLoader(
        model_path=str(mdir),
    )
    _init_loader(loader)
    assert loader.model.config.eos_token_id is not None
    assert loader.tokenizer.eos_token is not None
    out = _run(loader, "hello world", 8, 0.7)
    assert isinstance(out, str)
    assert out.strip() != ""
    n = _count_tokens(loader, out)
    assert 0 < n <= 8
