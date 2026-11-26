import random

import pytest

torch = pytest.importorskip("torch")

from apps.core.native.config import ZyrquenConfig
from apps.core.native.model import ZyrquenModel
from apps.core.native.train import TrainConfig, train

MCFG = ZyrquenConfig(vocab_size=64, max_seq_len=16, n_layers=2, n_heads=2, d_model=32, d_ff=64)


def _data():
    rng = random.Random(0)
    pattern = [rng.randrange(64) for _ in range(32)]
    return pattern * 40


def _cfg(steps):
    return TrainConfig(block_size=16, batch_size=8, max_steps=steps, warmup_steps=5, lr=3e-3,
                       min_lr=3e-4, eval_interval=steps, eval_batches=4,
                       checkpoint_interval=10, log_interval=5)


def test_training_reduces_loss(tmp_path):
    torch.manual_seed(0)
    ids = _data()
    model = ZyrquenModel(MCFG)
    result = train(model, ids, ids, _cfg(60), tmp_path / "ck", tmp_path / "log.jsonl")
    assert result["steps"] == 60 and result["val_loss"] < 3.0  # random baseline ~ ln(64)=4.16


def test_resume_continues_from_checkpoint(tmp_path):
    ids = _data()
    torch.manual_seed(0)
    train(ZyrquenModel(MCFG), ids, ids, _cfg(20), tmp_path / "ck", tmp_path / "log.jsonl")
    torch.manual_seed(1)
    result = train(ZyrquenModel(MCFG), ids, ids, _cfg(40), tmp_path / "ck", tmp_path / "log.jsonl")
    assert result["resumed_from"] == 20 and result["steps"] == 40
