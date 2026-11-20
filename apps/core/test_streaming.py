"""Phase 5.5 - Streaming Response.
Real-only, no mock.
Tiny fixture is pipeline check.
Not production weights.
"""
import asyncio
from pathlib import Path

import pytest

from apps.core.context import InferenceContext
from apps.core.model_loader import NativeModelLoader
from apps.core.streaming import StreamingInferenceEngine

def _init_loader(loader):
    if hasattr(loader, "initialize"):
        return loader.initialize()
    if hasattr(loader, "load"):
        return loader.load()
    raise AssertionError("no init")

async def _collect(engine, ctx):
    parts = []
    chunks = []
    async for c in engine.stream(ctx):
        chunks.append(c)
        if not c.is_final:
            parts.append(c.text)
    return "".join(parts), chunks

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

def test_01_stream_chunks(tmp_path):
    mdir = _make_tiny_model_dir(
        tmp_path / "tiny-55",
    )
    loader = NativeModelLoader(
        model_path=str(mdir),
    )
    _init_loader(loader)
    eng = StreamingInferenceEngine(loader)
    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt="hello world",
        max_tokens=8,
        temperature=0.0,
    )
    text, chunks = asyncio.run(
        _collect(eng, ctx),
    )
    content = [
        c for c in chunks if not c.is_final
    ]
    assert len(content) >= 1
    assert len(content) <= 8
    assert chunks[-1].is_final is True
    assert [
        c.index for c in content
    ] == list(range(len(content)))
    assert text == "".join(
        c.text for c in content
    )
    assert any(c.text for c in content)
    expected_input_tokens = loader.tokenizer(
        "hello world",
        return_tensors="pt",
        truncation=False,
    )["input_ids"].shape[-1]
    assert chunks[-1].input_tokens == expected_input_tokens
    assert chunks[-1].output_tokens == len(content)

def test_02_greedy_stream_deterministic(tmp_path):
    mdir = _make_tiny_model_dir(
        tmp_path / "tiny-55",
    )
    loader = NativeModelLoader(
        model_path=str(mdir),
    )
    _init_loader(loader)
    eng = StreamingInferenceEngine(loader)
    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt="hello world",
        max_tokens=8,
        temperature=0.0,
    )
    a, _ = asyncio.run(
        _collect(eng, ctx),
    )
    b, _ = asyncio.run(
        _collect(eng, ctx),
    )
    assert a == b
    assert isinstance(a, str)

def test_03_sampling_stream(tmp_path):
    mdir = _make_tiny_model_dir(
        tmp_path / "tiny-55",
    )
    loader = NativeModelLoader(
        model_path=str(mdir),
    )
    _init_loader(loader)
    eng = StreamingInferenceEngine(loader)
    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt="hello world",
        max_tokens=8,
        temperature=0.7,
        top_k=5,
        top_p=0.9,
    )
    text, chunks = asyncio.run(
        _collect(eng, ctx),
    )
    content = [
        c for c in chunks if not c.is_final
    ]
    assert len(content) <= 8
    assert isinstance(text, str)
    full = asyncio.run(
        eng.collect(ctx),
    )
    assert isinstance(full, str)

def test_04_not_ready_and_max_tokens(tmp_path):
    mdir = _make_tiny_model_dir(
        tmp_path / "tiny-55",
    )
    loader2 = NativeModelLoader(
        model_path=str(mdir),
    )
    eng2 = StreamingInferenceEngine(loader2)
    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt="hello world",
        max_tokens=8,
        temperature=0.0,
    )
    with pytest.raises(Exception):
        asyncio.run(
            _collect(eng2, ctx),
        )
    loader = NativeModelLoader(
        model_path=str(mdir),
    )
    _init_loader(loader)
    eng = StreamingInferenceEngine(loader)
    ctx4 = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt="hello world",
        max_tokens=4,
        temperature=0.0,
    )
    _, chunks = asyncio.run(
        _collect(eng, ctx4),
    )
    content = [
        c for c in chunks if not c.is_final
    ]
    assert len(content) <= 4
    assert chunks[-1].is_final is True
