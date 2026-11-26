import random

import pytest

from apps.core.native.dataset import PrepConfig, Source, prepare_dataset, load_split
from apps.core.native.tokenizer import BASE_VOCAB, ZyrquenTokenizer
from apps.core.native.train import (
    TrainConfig, build_token_stream, lr_at, perplexity, sample_batch)

CFG = TrainConfig(max_steps=100, warmup_steps=10, lr=1e-3, min_lr=1e-4)


def test_lr_schedule():
    assert lr_at(0, CFG) == pytest.approx(1e-4)          # warm-up start
    assert lr_at(9, CFG) == pytest.approx(1e-3)          # warm-up end
    assert lr_at(10, CFG) == pytest.approx(1e-3)         # cosine start
    assert lr_at(99, CFG) < 2e-4 and lr_at(100, CFG) == 1e-4
    vals = [lr_at(s, CFG) for s in range(10, 100)]
    assert all(a >= b for a, b in zip(vals, vals[1:]))   # monotone decay


def test_sample_batch_shift_and_determinism():
    ids = list(range(1000))
    x1, y1 = sample_batch(ids, 8, 4, random.Random(1))
    x2, _ = sample_batch(ids, 8, 4, random.Random(1))
    assert x1 == x2
    assert all(len(r) == 8 for r in x1)
    assert all(yy == [t + 1 for t in xx] for xx, yy in zip(x1, y1))
    with pytest.raises(ValueError):
        sample_batch([1, 2, 3], 8, 1, random.Random(0))


def test_config_validation():
    with pytest.raises(ValueError):
        TrainConfig(lr=1e-4, min_lr=1e-3)
    with pytest.raises(ValueError):
        TrainConfig(max_steps=10, warmup_steps=10)


def test_end_to_end_data_path(tmp_path):
    src = tmp_path / "d.jsonl"
    import json
    docs = [{"text": f"เอกสารตัวอย่างที่ {i} สำหรับทดสอบ and a sample document number {i} here"} for i in range(200)]
    src.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in docs), encoding="utf-8")
    prepare_dataset([Source(str(src), "test-declared")], tmp_path / "ds",
                    PrepConfig(val_fraction=0.1, test_fraction=0.1))
    tok = ZyrquenTokenizer.train(load_split(tmp_path / "ds", "train"), BASE_VOCAB + 80)
    ids = build_token_stream(load_split(tmp_path / "ds", "train"), tok)
    assert ids.count(tok.eos_id) == len(list(load_split(tmp_path / "ds", "train")))
    x, y = sample_batch(ids, 16, 2, random.Random(0))
    assert max(max(r) for r in x) < tok.vocab_size
    assert perplexity(0.0) == 1.0
