"""Compute Budget Controller for fair Baseline vs AEL comparison.

Tracks training steps, batch size, sandbox evaluations (including self-correction
retries), and wall-clock time so neither arm can silently exceed the agreed budget.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class ComputeBudget:
    max_training_steps: int
    batch_size: int
    max_sandbox_runs: int
    max_attempts_per_task: int = 2
    max_wall_time_sec: float = 180.0


class BudgetExhaustedError(RuntimeError):
    """Raised when an operation attempts to exceed the allocated compute budget."""


class BudgetController:
    """Enforces equal compute and sandbox-execution budgets per experiment arm."""

    def __init__(self, budget: ComputeBudget, *, arm_name: str) -> None:
        self.budget = budget
        self.arm_name = arm_name
        self.training_steps_used: int = 0
        self.examples_processed: int = 0
        self.sandbox_runs_used: int = 0
        self.first_pass_runs: int = 0
        self.retry_runs_used: int = 0
        self.retries_skipped_by_policy: int = 0
        self.started_at: float = time.monotonic()
        self.finished_at: float | None = None

    def elapsed_sec(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return round(max(0.0, end - self.started_at), 4)

    def remaining_training_steps(self) -> int:
        return max(0, self.budget.max_training_steps - self.training_steps_used)

    def remaining_sandbox_runs(self) -> int:
        return max(0, self.budget.max_sandbox_runs - self.sandbox_runs_used)

    def allocate_training_steps(self, requested: int) -> int:
        allowed = min(max(0, int(requested)), self.remaining_training_steps())
        return allowed

    def record_training_steps(self, steps_executed: int, batch_size: int) -> None:
        steps = int(steps_executed)
        if steps < 0:
            raise ValueError("steps_executed cannot be negative")
        if self.training_steps_used + steps > self.budget.max_training_steps:
            raise BudgetExhaustedError(
                f"[{self.arm_name}] Training step budget exceeded: "
                f"{self.training_steps_used + steps} > {self.budget.max_training_steps}"
            )
        self.training_steps_used += steps
        self.examples_processed += steps * int(batch_size)

    def try_consume_sandbox_run(self, *, is_retry: bool) -> bool:
        if self.sandbox_runs_used + 1 > self.budget.max_sandbox_runs:
            return False
        self.sandbox_runs_used += 1
        if is_retry:
            self.retry_runs_used += 1
        else:
            self.first_pass_runs += 1
        return True

    def record_skipped_retry(self) -> None:
        self.retries_skipped_by_policy += 1

    def finish(self) -> None:
        if self.finished_at is None:
            self.finished_at = time.monotonic()

    def summary(self) -> Dict[str, Any]:
        return {
            "arm_name": self.arm_name,
            "budget": asdict(self.budget),
            "training_steps_used": self.training_steps_used,
            "examples_processed": self.examples_processed,
            "sandbox_runs_used": self.sandbox_runs_used,
            "first_pass_runs": self.first_pass_runs,
            "retry_runs_used": self.retry_runs_used,
            "retries_skipped_by_policy": self.retries_skipped_by_policy,
            "wall_time_sec": self.elapsed_sec(),
            "within_training_budget": self.training_steps_used <= self.budget.max_training_steps,
            "within_sandbox_budget": self.sandbox_runs_used <= self.budget.max_sandbox_runs,
        }
