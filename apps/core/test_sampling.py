"""Phase 5.3 / Phase 10 - Native Sampling Engine.
Real-only, no mock.
Tiny fixture is pipeline check. Not ZYRQUEN trained production weights.
"""
import asyncio
from pathlib import Path

import pytest

from apps.api.routers.inference import InferenceRequest
from apps.core.context import InferenceContext
from apps.core.inference import NativeInferenceEngine
from apps.core.model_loader import NativeModelLoader
from apps.core.test_inference import _init_loader, _make_tiny_model_dir


def _make_engine(loader):
    return NativeInferenceEngine(loader)


def _run(loader, prompt: str, max_t: int, temp: float, tk: int, tp: float) -> str:
    engine = _make_engine(loader)
    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt=prompt,
        max_tokens=max_t,
        temperature=temp,
        top_k=tk,
        top_p=tp,
    )
    return asyncio.run(engine.execute(ctx))


def test_01_defaults_and_validation():
    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt="hello world",
    )
    assert ctx.top_k == 0
    assert ctx.top_p == 1.0
    req = InferenceRequest(
        prompt="hello world",
        request_id="123e4567-e89b-42d3-a456-426614174000",
    )
    assert req.top_k == 0
    assert req.top_p == 1.0
    with pytest.raises(Exception):
        InferenceContext(
            user_id="00000000-0000-0000-0000-000000000001",
            prompt="hello",
            top_k=-1,
        )
    with pytest.raises(Exception):
        InferenceContext(
            user_id="00000000-0000-0000-0000-000000000001",
            prompt="hello",
            top_p=1.5,
        )


def test_02_top_k_generate(tmp_path: Path):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-53")
    loader = NativeModelLoader(model_path=str(mdir))
    _init_loader(loader)
    out = _run(loader, "hello world", 8, 0.7, 5, 1.0)
    assert isinstance(out, str)
    assert out.strip() != ""


def test_03_top_p_generate(tmp_path: Path):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-53")
    loader = NativeModelLoader(model_path=str(mdir))
    _init_loader(loader)
    out = _run(loader, "hello world", 8, 0.7, 0, 0.9)
    assert isinstance(out, str)
    assert out.strip() != ""


def test_04_top_k_1_deterministic(tmp_path: Path):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-53")
    loader = NativeModelLoader(model_path=str(mdir))
    _init_loader(loader)
    a = _run(loader, "hello world", 8, 0.7, 1, 1.0)
    b = _run(loader, "hello world", 8, 0.7, 1, 1.0)
    assert a == b
    c = _run(loader, "hello world", 8, 0.7, 5, 0.9)
    assert isinstance(c, str)
    assert c.strip() != ""
