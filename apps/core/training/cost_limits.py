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
