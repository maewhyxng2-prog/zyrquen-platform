"""Phase 5.2 / Phase 10 - Native Token Generation.
Real-only, no mock.
Tiny fixture is pipeline check. Not ZYRQUEN trained production weights.
"""
import asyncio
from pathlib import Path

from apps.core.context import InferenceContext
from apps.core.inference import NativeInferenceEngine
from apps.core.model_loader import NativeModelLoader
from apps.core.test_inference import _init_loader, _make_tiny_model_dir


def _make_engine(loader):
    return NativeInferenceEngine(loader)


def _count_tokens(loader, text: str) -> int:
    return len(loader.tokenizer.encode(text, add_bos=False, add_eos=False))


def _run(loader, prompt: str, max_t: int, temp: float) -> str:
    engine = _make_engine(loader)
    ctx = InferenceContext(
        user_id="00000000-0000-0000-0000-000000000001",
        prompt=prompt,
        max_tokens=max_t,
        temperature=temp,
    )
    return asyncio.run(engine.execute(ctx))


def test_01_max_tokens_respected(tmp_path: Path):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-52")
    loader = NativeModelLoader(model_path=str(mdir))
    _init_loader(loader)
    out = _run(loader, "hello world", 4, 0.0)
    assert isinstance(out, str)
    assert out.strip() != ""
    n = _count_tokens(loader, out)
    assert 0 < n <= 4


def test_02_continuous_generation(tmp_path: Path):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-52")
    loader = NativeModelLoader(model_path=str(mdir))
    _init_loader(loader)
    short = _run(loader, "hello world", 2, 0.0)
    long = _run(loader, "hello world", 12, 0.0)
    ns = _count_tokens(loader, short)
    nl = _count_tokens(loader, long)
    assert ns <= 2
    assert nl <= 12
    assert nl >= ns


def test_03_greedy_deterministic(tmp_path: Path):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-52")
    loader = NativeModelLoader(model_path=str(mdir))
    _init_loader(loader)
    a = _run(loader, "hello world", 8, 0.0)
    b = _run(loader, "hello world", 8, 0.0)
    assert a == b


def test_04_sampling_and_eos(tmp_path: Path):
    mdir = _make_tiny_model_dir(tmp_path / "tiny-52")
    loader = NativeModelLoader(model_path=str(mdir))
    _init_loader(loader)
    assert loader.model.cfg.max_seq_len > 0
    assert loader.tokenizer.eos_id is not None
    out = _run(loader, "hello world", 8, 0.7)
    assert isinstance(out, str)
    assert out.strip() != ""
    n = _count_tokens(loader, out)
    assert 0 < n <= 8
