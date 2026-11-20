import time
from dataclasses import dataclass
from typing import Callable


class LimitExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class CostLimits:
    hourly_rate_usd: float          # price of the whole machine per hour
    max_budget_usd: float | None = None
    max_runtime_seconds: float | None = None
    max_gpu_hours: float | None = None
    gpu_count: int = 1

    def __post_init__(self):
        if self.hourly_rate_usd < 0 or self.gpu_count < 1:
            raise ValueError("invalid hourly_rate_usd or gpu_count")
        for name in ("max_budget_usd", "max_runtime_seconds", "max_gpu_hours"):
            v = getattr(self, name)
            if v is not None and v <= 0:
                raise ValueError(f"{name} must be positive")


class CostController:
    """Tracks runtime / GPU-hours / spend and tells the trainer when to stop."""

    def __init__(self, limits: CostLimits, clock: Callable[[], float] = time.monotonic):
        self.limits = limits
        self._clock = clock
        self._started: float | None = None
        self._accumulated = 0.0

    def start(self) -> None:
        if self._started is None:
            self._started = self._clock()

    def pause(self) -> None:
        if self._started is not None:
            self._accumulated += self._clock() - self._started
            self._started = None

    def elapsed_seconds(self) -> float:
        running = (self._clock() - self._started) if self._started is not None else 0.0
        return self._accumulated + running

    def snapshot(self) -> dict:
        sec = self.elapsed_seconds()
        hours = sec / 3600.0
        return {
            "elapsed_seconds": sec,
            "gpu_hours": hours * self.limits.gpu_count,
            "cost_usd": hours * self.limits.hourly_rate_usd,
        }

    def exceeded(self) -> str | None:
        s, lim = self.snapshot(), self.limits
        if lim.max_runtime_seconds is not None and s["elapsed_seconds"] >= lim.max_runtime_seconds:
            return "max_runtime_seconds"
        if lim.max_gpu_hours is not None and s["gpu_hours"] >= lim.max_gpu_hours:
            return "max_gpu_hours"
        if lim.max_budget_usd is not None and s["cost_usd"] >= lim.max_budget_usd:
            return "max_budget_usd"
        return None

    def should_stop(self) -> bool:
        return self.exceeded() is not None

    def enforce(self) -> None:
        reason = self.exceeded()
        if reason:
            raise LimitExceeded(f"{reason} reached: {self.snapshot()}")
