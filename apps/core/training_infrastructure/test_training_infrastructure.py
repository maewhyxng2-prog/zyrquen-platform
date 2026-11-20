import json
import math

import pytest

from apps.core.training_infrastructure.cost.cost_controller import (
    CostController, CostLimits, LimitExceeded)
from apps.core.training_infrastructure.distributed.trainer import DistConfig
from apps.core.training_infrastructure.gpu.provisioner import LocalProvider, ProvisioningError
from apps.core.training_infrastructure.gpu.resource_manager import ResourceManager
from apps.core.training_infrastructure.monitoring.training_monitor import TrainingMonitor
from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
    CheckpointManager, capture_rng_state, restore_rng_state)
from apps.core.training_infrastructure.validation.model_validator import ModelValidator


def _save(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _mgr(path, keep=3):
    return CheckpointManager(path, keep_last=keep, save_fn=_save, load_fn=_load)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


# ---- cost ----
def test_cost_runtime_limit():
    clk = Clock()
    c = CostController(CostLimits(hourly_rate_usd=2.0, max_runtime_seconds=100), clk)
    c.start()
    clk.t = 99
    assert not c.should_stop()
    clk.t = 100
    assert c.exceeded() == "max_runtime_seconds"
    with pytest.raises(LimitExceeded):
        c.enforce()


def test_cost_budget_and_gpu_hours():
    clk = Clock()
    c = CostController(CostLimits(hourly_rate_usd=4.0, max_budget_usd=2.0, gpu_count=2), clk)
    c.start()
    clk.t = 1800  # 0.5h -> $2.00, 1 gpu-hour
    assert c.snapshot() == {"elapsed_seconds": 1800, "gpu_hours": 1.0, "cost_usd": 2.0}
    assert c.exceeded() == "max_budget_usd"
    c2 = CostController(CostLimits(hourly_rate_usd=1.0, max_gpu_hours=1.0, gpu_count=2), clk)
    c2.start()
    assert c2.exceeded() is None
    clk.t = 3600 + 1800
    assert c2.exceeded() == "max_gpu_hours"


def test_cost_pause_stops_clock_and_validation():
    clk = Clock()
    c = CostController(CostLimits(hourly_rate_usd=1.0), clk)
    c.start(); clk.t = 10; c.pause(); clk.t = 500
    assert c.elapsed_seconds() == 10
    with pytest.raises(ValueError):
        CostLimits(hourly_rate_usd=1.0, max_budget_usd=0)


# ---- gpu ----
def test_resource_manager_parses_nvidia_smi():
    out = "0, NVIDIA A100, 40960, 1024, 7\n1, NVIDIA A100, 40960, 40000, 99\n"
    rm = ResourceManager(runner=lambda cmd: out)
    gpus = rm.list_gpus()
    assert [g.index for g in gpus] == [0, 1]
    assert rm.free_memory_mb(0) == 39936 and rm.select_device() == "cuda"


def test_resource_manager_no_gpu():
    def boom(cmd):
        raise FileNotFoundError("nvidia-smi")
    rm = ResourceManager(runner=boom)
    assert rm.list_gpus() == [] and rm.select_device() == "cpu"


def test_provisioner():
    ok = LocalProvider(ResourceManager(runner=lambda c: "0, T4, 15360, 0, 0\n"))
    m = ok.provision()
    assert m.status == "ready" and ok.release(m).status == "released"
    none = LocalProvider(ResourceManager(runner=lambda c: ""))
    with pytest.raises(ProvisioningError):
        none.provision()


# ---- distributed ----
def test_dist_config():
    assert not DistConfig.from_env({}).is_distributed
    cfg = DistConfig.from_env({"RANK": "1", "WORLD_SIZE": "4", "LOCAL_RANK": "1"})
    assert cfg.is_distributed and not cfg.is_main
    with pytest.raises(ValueError):
        DistConfig(rank=4, world_size=4)


# ---- monitoring ----
def test_monitor(tmp_path):
    clk = Clock()
    mon = TrainingMonitor(tmp_path / "m.jsonl", clk)
    mon.log(1, 3.0, 1e-3, tokens=100)
    clk.t = 2
    r = mon.log(2, 2.5, 1e-3, tokens=100)
    assert r["tokens_per_sec"] == 50
    mon.log(3, float("nan"), 1e-3)
    with open(tmp_path / "m.jsonl", "a", encoding="utf-8") as f:
        f.write('{"step": 4, "lo')  # torn line from a crash
    s = mon.summary()
    assert s["records"] == 3 and s["diverged"] and s["best_loss"] == 2.5


# ---- recovery ----
def test_checkpoint_roundtrip_and_prune(tmp_path):
    m = _mgr(tmp_path, keep=2)
    for step in (10, 20, 30):
        m.save(step, {"step": step, "w": [step]})
    step, state = m.load_latest()
    assert step == 30 and state["w"] == [30]
    assert not (tmp_path / "ckpt_00000010.pt").exists()


def test_checkpoint_skips_corrupt_latest(tmp_path):
    m = _mgr(tmp_path)
    m.save(10, {"w": [10]})
    m.save(20, {"w": [20]})
    (tmp_path / "ckpt_00000020.pt").write_text("garbage", encoding="utf-8")
    step, state = m.load_latest()
    assert step == 10 and state["w"] == [10]


def test_checkpoint_empty_and_rng(tmp_path):
    assert _mgr(tmp_path).load_latest() is None
    import random
    st = capture_rng_state()
    a = random.random()
    restore_rng_state(st)
    assert random.random() == a


# ---- validation ----
def test_validator(tmp_path):
    m = _mgr(tmp_path)
    m.save(5, {"w": [1]})
    v = ModelValidator(max_val_loss=4.0, max_perplexity=60.0)
    assert v.validate(tmp_path, {"val_loss": 3.2, "perplexity": math.exp(3.2)}).passed
    bad = v.validate(tmp_path, {"val_loss": 5.0, "perplexity": 150.0})
    assert not bad.passed
    assert not v.validate(tmp_path, {"val_loss": float("nan")}).passed
    (tmp_path / "ckpt_00000005.pt").write_text("x", encoding="utf-8")
    assert not v.validate(tmp_path, {"val_loss": 3.2, "perplexity": 20.0}).passed
    empty = tmp_path / "empty"
    assert not ModelValidator().validate(empty, {"val_loss": 1.0}).passed
