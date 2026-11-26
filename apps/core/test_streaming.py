"""Phase 5.5 / Phase 10 - Native Streaming Response.
Real-only, no mock.
Tiny fixture is pipeline check. Not ZYRQUEN trained production weights.
"""
import asyncio
from pathlib import Path

import pytest

from apps.core.context import InferenceContext
from apps.core.model_loader import NativeModelLoader
from apps.core.streaming import StreamingInferenceEngine
from apps.core.test_inference import _init_loader, _make_tiny_model_dir


async def _collect(engine, ctx):
    parts = []
    chunks = []
    async for chunk in engine.stream(ctx):
        chunks.append(chunk)
        if not chunk.is_final:
            parts.append(chunk.text)
    return "".join(parts), chunks


def test_01_stream_chunks(tmp_path: Path):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-55")
    loader = NativeModelLoader(model_path=str(mdir))
    _init_loader(loader)
    eng = StreamingInferenceEngine(loader)
    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt="hello world",
        max_tokens=8,
        temperature=0.0,
    )
    text, chunks = asyncio.run(_collect(eng, ctx))
    content = [c for c in chunks if not c.is_final]
    assert len(content) >= 1
    assert len(content) <= 8
    assert chunks[-1].is_final is True
    assert [c.index for c in content] == list(range(len(content)))
    assert text == "".join(c.text for c in content)
    assert any(c.text for c in content)
    expected_input_tokens = len(loader.tokenizer.encode("hello world"))
    assert chunks[-1].input_tokens == expected_input_tokens
    assert chunks[-1].output_tokens == len(content)


def test_02_greedy_stream_deterministic(tmp_path: Path):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-55")
    loader = NativeModelLoader(model_path=str(mdir))
    _init_loader(loader)
    eng = StreamingInferenceEngine(loader)
    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt="hello world",
        max_tokens=8,
        temperature=0.0,
    )
    a, _ = asyncio.run(_collect(eng, ctx))
    b, _ = asyncio.run(_collect(eng, ctx))
    assert a == b
    assert isinstance(a, str)


def test_03_sampling_stream(tmp_path: Path):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-55")
    loader = NativeModelLoader(model_path=str(mdir))
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
    text, chunks = asyncio.run(_collect(eng, ctx))
    content = [c for c in chunks if not c.is_final]
    assert len(content) <= 8
    assert isinstance(text, str)
    full = asyncio.run(eng.collect(ctx))
    assert isinstance(full, str)


def test_04_not_ready_and_max_tokens(tmp_path: Path):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-55")
    loader2 = NativeModelLoader(model_path=str(mdir))
    eng2 = StreamingInferenceEngine(loader2)
    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt="hello world",
        max_tokens=8,
        temperature=0.0,
    )
    with pytest.raises(Exception):
        asyncio.run(_collect(eng2, ctx))
    loader = NativeModelLoader(model_path=str(mdir))
    _init_loader(loader)
    eng = StreamingInferenceEngine(loader)
    ctx4 = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt="hello world",
        max_tokens=4,
        temperature=0.0,
    )
    _, chunks = asyncio.run(_collect(eng, ctx4))
    content = [c for c in chunks if not c.is_final]
    assert len(content) <= 4
    assert chunks[-1].is_final is True
