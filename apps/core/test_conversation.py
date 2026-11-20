"""Phase 5.4 - Context Management.
Real-only, no mock.
Tiny fixture is pipeline check.
Not production weights.
"""
import asyncio
from pathlib import Path

import pytest

from apps.core.conversation import (
    ChatMessage,
    ContextManager,
    ConversationHistory,
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

def test_01_order_and_validation():
    h = ConversationHistory(
        max_turns=2,
    )
    h.add_user("hello")
    h.add_assistant("hi there")
    h.add_user("again")
    assert len(h) == 2
    msgs = h.messages()
    assert msgs[0].content == "hi there"
    assert msgs[1].content == "again"
    assert msgs[0].role == "assistant"
    with pytest.raises(Exception):
        h.add("bad", "hi")
    with pytest.raises(Exception):
        ChatMessage(
            role="user",
            content="",
        )
    with pytest.raises(Exception):
        ChatMessage(
            role="bad",
            content="hi",
        )

def test_02_build_prompt_and_context():
    m = ContextManager(
        max_turns=10,
    )
    m.add_user("hello")
    m.add_assistant("hi there")
    full = m.build_prompt(
        "how are you",
    )
    assert "user: hello" in full
    assert "assistant: hi there" in full
    assert "user: how are you" in full
    assert full.endswith("assistant:")
    ctx = m.build_context(
        "00000000-0000-0000-0000-000000000001",
        "how are you",
        max_tokens=16,
        temperature=0.0,
        top_k=5,
        top_p=0.9,
    )
    assert "user: hello" in ctx.prompt
    assert ctx.max_tokens == 16
    assert ctx.top_k == 5
    assert ctx.top_p == 0.9
    with pytest.raises(Exception):
        m.build_prompt("   ")

def test_03_max_chars_drops_oldest():
    m = ContextManager(
        max_turns=10,
        max_chars=200,
    )
    m.add_user("old-" + "x" * 100)
    m.add_assistant("mid-" + "y" * 100)
    full = m.build_prompt("new")
    assert "old-" not in full
    assert "mid-" in full
    assert "user: new" in full
    assert len(full) <= 200
    m2 = ContextManager(
        max_turns=2,
    )
    m2.add_user("a")
    m2.add_user("b")
    m2.add_user("c")
    assert len(m2) == 2
    assert m2.messages()[0].content == "b"

def test_04_engine_with_context(tmp_path):
    mdir = _make_tiny_model_dir(
        tmp_path / "tiny-54",
    )
    loader = NativeModelLoader(
        model_path=str(mdir),
    )
    _init_loader(loader)
    m = ContextManager(
        max_turns=10,
    )
    m.add_user("hello world")
    ctx = m.build_context(
        "00000000-0000-0000-0000-000000000001",
        "hello world",
        max_tokens=8,
        temperature=0.0,
    )
    engine = _make_engine(loader)
    out = asyncio.run(
        engine.execute(ctx),
    )
    assert isinstance(out, str)
    assert out.strip() != ""
    m.add_assistant(out)
    assert len(m) == 2
    second = m.build_prompt("next")
    assert "hello world" in second
    assert out.strip()[:10] in second
