#!/bin/bash
# Run from the repository root. Adds cost limits to training runs.
set -e
test -f apps/core/training/orchestrator.py || { echo "run from repo root"; exit 1; }
test ! -e apps/core/training/cost_limits.py || { echo "cost_limits.py already exists - stop"; exit 1; }
grep -q "_cost_controller_from_env" apps/core/training/orchestrator.py && { echo "already patched - stop"; exit 1; }

cat > apps/core/training/cost_limits.py <<'EOF'
"""Builds the Phase 4 CostController for a training run from environment variables.

ZYRQUEN_TRAINING_HOURLY_RATE_USD   price of the whole machine per hour (needed for a budget)
ZYRQUEN_TRAINING_MAX_BUDGET_USD    stop when estimated spend reaches this
ZYRQUEN_TRAINING_MAX_RUNTIME_SECONDS  stop after this many seconds (per run invocation)
ZYRQUEN_TRAINING_MAX_GPU_HOURS     stop after this many GPU-hours
ZYRQUEN_TRAINING_GPU_COUNT         GPUs on the machine (default 1)

If no limit is set at all, a conservative default of 1 hour is applied (fail closed).
"""
import os

from apps.core.training_infrastructure.cost.cost_controller import CostController, CostLimits

DEFAULT_MAX_RUNTIME_SECONDS = 3600.0


def _number(env, name):
    raw = str(env.get(name, "")).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number") from None


def cost_controller_from_env(env=None, clock=None) -> CostController:
    env = os.environ if env is None else env
    rate = _number(env, "ZYRQUEN_TRAINING_HOURLY_RATE_USD")
    budget = _number(env, "ZYRQUEN_TRAINING_MAX_BUDGET_USD")
    runtime = _number(env, "ZYRQUEN_TRAINING_MAX_RUNTIME_SECONDS")
    gpu_hours = _number(env, "ZYRQUEN_TRAINING_MAX_GPU_HOURS")
    gpus = int(_number(env, "ZYRQUEN_TRAINING_GPU_COUNT") or 1)

    if budget is not None and rate is None:
        raise ValueError("ZYRQUEN_TRAINING_MAX_BUDGET_USD requires ZYRQUEN_TRAINING_HOURLY_RATE_USD")
    if runtime is None and gpu_hours is None and budget is None:
        runtime = DEFAULT_MAX_RUNTIME_SECONDS

    limits = CostLimits(hourly_rate_usd=rate or 0.0, max_budget_usd=budget,
                        max_runtime_seconds=runtime, max_gpu_hours=gpu_hours, gpu_count=gpus)
    return CostController(limits) if clock is None else CostController(limits, clock)
EOF

cat > apps/core/training/test_cost_limits.py <<'EOF'
import pytest

from apps.core.training.cost_limits import DEFAULT_MAX_RUNTIME_SECONDS, cost_controller_from_env


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_default_is_one_hour_fail_closed():
    clk = Clock()
    c = cost_controller_from_env({}, clk)
    c.start()
    clk.t = DEFAULT_MAX_RUNTIME_SECONDS - 1
    assert not c.should_stop()
    clk.t = DEFAULT_MAX_RUNTIME_SECONDS
    assert c.exceeded() == "max_runtime_seconds"


def test_budget_with_rate():
    clk = Clock()
    c = cost_controller_from_env({"ZYRQUEN_TRAINING_HOURLY_RATE_USD": "4",
                                  "ZYRQUEN_TRAINING_MAX_BUDGET_USD": "2"}, clk)
    c.start()
    clk.t = 1800
    assert c.exceeded() == "max_budget_usd"


def test_budget_without_rate_is_rejected():
    with pytest.raises(ValueError):
        cost_controller_from_env({"ZYRQUEN_TRAINING_MAX_BUDGET_USD": "5"})


def test_bad_and_nonpositive_values_rejected():
    with pytest.raises(ValueError):
        cost_controller_from_env({"ZYRQUEN_TRAINING_MAX_RUNTIME_SECONDS": "abc"})
    with pytest.raises(ValueError):
        cost_controller_from_env({"ZYRQUEN_TRAINING_MAX_RUNTIME_SECONDS": "0"})


def test_gpu_hours_with_gpu_count():
    clk = Clock()
    c = cost_controller_from_env({"ZYRQUEN_TRAINING_MAX_GPU_HOURS": "2",
                                  "ZYRQUEN_TRAINING_GPU_COUNT": "4"}, clk)
    c.start()
    clk.t = 1800  # 0.5h * 4 gpus = 2 gpu-hours
    assert c.exceeded() == "max_gpu_hours"
EOF

python3 - <<'EOF'
p = "apps/core/training/orchestrator.py"
s = open(p, encoding="utf-8").read()
old = "            dataset_version=prepared.dataset_version,\n        )"
assert s.count(old) == 1, "call site not found exactly once - nothing changed"
s = s.replace(old, "            dataset_version=prepared.dataset_version,\n            cost_controller=_cost_controller_from_env(),\n        )")
s = s.rstrip("\n") + '''


def _cost_controller_from_env():
    from apps.core.training.cost_limits import cost_controller_from_env

    return cost_controller_from_env()
'''
open(p, "w", encoding="utf-8").write(s)
print("patched orchestrator.py")
EOF
echo "done - now run: python -m pytest -q apps/core/training"
