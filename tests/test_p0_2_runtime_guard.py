"""P0-2 regression: orchestrator must enforce TrainingRuntimeGuard (no training/inference)."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.core.training import orchestrator as orch_mod
from apps.core.workflow import resource_guard as rg_mod
from apps.core.native import train as train_mod


class _FakeUsage:
    def __init__(self, free_gb: float):
        self.free = int(free_gb * 1024**3)
        self.total = int(16 * 1024**3)
        self.used = self.total - self.free


def _make_guard(tmp_path, **over):
    kwargs = dict(
        checkpoint_dir=str(tmp_path / "ckpt"),
        clock=lambda: over.get("now", 1000.0),
        rss_reader=lambda: int(over.get("rss_gb", 1.0) * 1024**3),
        disk_usage_fn=lambda _p: _FakeUsage(over.get("free_gb", 10.0)),
    )
    for k in ("experiment_timeout_sec", "loop_timeout_sec", "loop_started_at",
              "ram_soft_gb", "ram_hard_gb", "disk_reserve_gb",
              "max_new_disk_gb", "cpu_threads", "audit_logger",
              "run_id", "step_key"):
        if k in over:
            kwargs[k] = over[k]
    return rg_mod.TrainingRuntimeGuard(**kwargs)


def test_cpu_steps_cap_is_single_value():
    assert orch_mod.MAX_CPU_TRAINING_STEPS == rg_mod.MAX_CPU_TRAINING_STEPS == 500, (
        f"steps cap diverged: orchestrator={orch_mod.MAX_CPU_TRAINING_STEPS} "
        f"guard={rg_mod.MAX_CPU_TRAINING_STEPS}"
    )


def test_orchestrator_run_wires_runtime_guard_and_fails_closed():
    src = inspect.getsource(orch_mod.TrainingOrchestrator.run)
    assert "TrainingRuntimeGuard" in src, "run() must construct TrainingRuntimeGuard"
    assert "runtime_guard=runtime_guard" in src or "runtime_guard = " in src or "runtime_guard=" in src, (
        "run() must pass runtime_guard to train/train_sft"
    )
    assert "stopped_reason" in src, "run() must fail closed on guard stopped_reason"


def test_train_entrypoints_accept_runtime_guard():
    for fn in (train_mod.train, train_mod.train_sft):
        sig = inspect.signature(fn)
        assert "runtime_guard" in sig.parameters, f"{fn.__name__} must accept runtime_guard"


def test_guard_blocks_ram_hard_limit(tmp_path):
    g = _make_guard(tmp_path, rss_gb=4.0)
    ok, reason, _snap = g.check_runtime("before_step", step=1)
    assert ok is False and reason == "ram_hard_limit"


def test_guard_blocks_disk_reserve(tmp_path):
    g = _make_guard(tmp_path, free_gb=0.5)
    ok, reason, _snap = g.check_runtime("before_checkpoint", step=1, checkpoint_write=True)
    assert ok is False and reason == "disk_reserve_violated"


def test_guard_blocks_loop_and_experiment_timeout(tmp_path):
    g = _make_guard(tmp_path, now=5000.0, loop_started_at=0.0)
    ok, reason, _snap = g.check_runtime("before_step", step=1)
    assert ok is False and reason in {"loop_timeout", "experiment_timeout"}


def test_guard_soft_warning_and_audit(tmp_path):
    events: list = []

    class _Audit:
        def record(self, **kw):
            events.append(kw)

    g = _make_guard(tmp_path, rss_gb=3.2, audit_logger=_Audit())
    ok, _reason, snap = g.check_runtime("before_step", step=1)
    assert ok is True
    assert snap.get("soft_warning_triggered") is True
    assert any(e.get("event_type") == "training.ram_soft_warning" for e in events)
