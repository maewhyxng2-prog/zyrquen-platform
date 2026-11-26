"""Autonomous Training Loop — Wrapper only.

No new Trainer / Registry / Approval Gate / Resource Guard.
Reuses: handlers.groups, governance, resource_guard,
native.train.TrainConfig, native.checkpoint.VersionedCheckpointManager.
"""
from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from apps.core.workflow.resource_guard import (
    GB,
    MAX_CPU_BATCH_SIZE,
    MAX_CPU_MODEL_PARAMETERS,
    MAX_CPU_SEQUENCE_LENGTH,
    MAX_CPU_THREADS,
    MAX_CPU_TRAINING_STEPS,
    MAX_EXPERIMENT_TIMEOUT_SECONDS,
    MAX_LOOP_TIMEOUT_SECONDS,
    MAX_NEW_DISK_GB,
    MIN_DISK_RESERVE_GB,
    RAM_HARD_LIMIT_GB,
    RAM_SOFT_LIMIT_GB,
    TrainingRuntimeGuard,
    check_disk_reserve,
    enforce_cpu_thread_cap,
    read_process_rss_bytes,
)

# Re-exported Resource Budget Lock constants (canonical source: resource_guard.py)
MAX_PARAMS = MAX_CPU_MODEL_PARAMETERS
MAX_SEQ = MAX_CPU_SEQUENCE_LENGTH
MAX_BATCH = MAX_CPU_BATCH_SIZE
MAX_STEPS = MAX_CPU_TRAINING_STEPS
RAM_SOFT_GB = RAM_SOFT_LIMIT_GB
RAM_HARD_GB = RAM_HARD_LIMIT_GB
DISK_RESERVE_GB = MIN_DISK_RESERVE_GB
MAX_CHECKPOINTS_PER_RUN = 10


def map_verdict_to_status(verdict: str, *, error_code: str | None = None) -> str:
    """Implementation A mapping: PASS->COMPLETED, WAITING_RESOURCE/NOT RUN/BLOCKED, FAIL->FAILED."""
    if verdict == "PASS":
        return "COMPLETED"
    if verdict == "WAITING_RESOURCE":
        return "WAITING_RESOURCE"
    if error_code == "disk_reserve_violated" and verdict == "BLOCKED":
        return "BLOCKED"
    if verdict in ("NOT RUN", "BLOCKED"):
        return "BLOCKED"
    if verdict == "FAIL":
        return "FAILED"
    return "BLOCKED"


def validate_budget(
    params: int,
    seq_len: int,
    batch_size: int,
    steps: int,
    *,
    cpu_threads: int = MAX_CPU_THREADS,
    experiment_timeout_sec: float = MAX_EXPERIMENT_TIMEOUT_SECONDS,
    loop_timeout_sec: float = MAX_LOOP_TIMEOUT_SECONDS,
) -> tuple[bool, str | None]:
    if params < 0:
        return False, "budget values must be > 0"
    if params != 0 and params > MAX_PARAMS:
        return False, f"params {params} > {MAX_PARAMS}"
    if seq_len > MAX_SEQ:
        return False, f"seq_len {seq_len} > {MAX_SEQ}"
    if batch_size > MAX_BATCH:
        return False, f"batch_size {batch_size} > {MAX_BATCH}"
    if steps > MAX_STEPS:
        return False, f"steps {steps} > {MAX_STEPS}"
    if seq_len <= 0 or batch_size <= 0 or steps <= 0:
        return False, "budget values must be > 0"
    if cpu_threads <= 0 or cpu_threads > MAX_CPU_THREADS:
        return False, f"cpu_threads {cpu_threads} > {MAX_CPU_THREADS}"
    if experiment_timeout_sec <= 0 or experiment_timeout_sec > MAX_EXPERIMENT_TIMEOUT_SECONDS:
        return False, f"experiment_timeout_sec {experiment_timeout_sec} > {MAX_EXPERIMENT_TIMEOUT_SECONDS}"
    if loop_timeout_sec <= 0 or loop_timeout_sec > MAX_LOOP_TIMEOUT_SECONDS:
        return False, f"loop_timeout_sec {loop_timeout_sec} > {MAX_LOOP_TIMEOUT_SECONDS}"
    return True, None


def read_rss_bytes() -> int:
    return read_process_rss_bytes()


class RamMonitor(threading.Thread):
    """Lightweight RSS poller and synchronous threshold checker around handle_training_execute."""

    def __init__(
        self,
        interval_s: float = 0.5,
        *,
        soft_limit_gb: float = RAM_SOFT_GB,
        hard_limit_gb: float = RAM_HARD_GB,
        rss_reader: Callable[[], int] = read_rss_bytes,
        on_soft_limit: Callable[[dict[str, Any]], None] | None = None,
        on_hard_limit: Callable[[dict[str, Any]], None] | None = None,
    ):
        super().__init__(daemon=True)
        self.interval_s = interval_s
        self.soft_limit_gb = float(soft_limit_gb)
        self.hard_limit_gb = float(hard_limit_gb)
        self.rss_reader = rss_reader
        self.on_soft_limit = on_soft_limit
        self.on_hard_limit = on_hard_limit
        self.peak_bytes = 0
        self.exceeded_soft = False
        self.exceeded_hard = False
        self._soft_notified = False
        self._hard_notified = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def check_now(self) -> dict[str, Any]:
        rss = int(self.rss_reader() or 0)
        soft_cb = None
        hard_cb = None
        with self._lock:
            if rss > self.peak_bytes:
                self.peak_bytes = rss
            if rss >= self.soft_limit_gb * GB:
                self.exceeded_soft = True
                if not self._soft_notified:
                    self._soft_notified = True
                    soft_cb = self.on_soft_limit
            if rss >= self.hard_limit_gb * GB:
                self.exceeded_hard = True
                if not self._hard_notified:
                    self._hard_notified = True
                    hard_cb = self.on_hard_limit
            snap = {
                "rss_gb": round(rss / GB, 4),
                "peak_gb": round(self.peak_bytes / GB, 4),
                "exceeded_soft": self.exceeded_soft,
                "exceeded_hard": self.exceeded_hard,
            }
        if soft_cb is not None:
            try:
                soft_cb(snap)
            except Exception:
                pass
        if hard_cb is not None:
            try:
                hard_cb(snap)
            except Exception:
                pass
        return snap

    def run(self) -> None:
        while not self._stop_event.is_set():
            snap = self.check_now()
            if snap["exceeded_hard"]:
                break
            self._stop_event.wait(self.interval_s)

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout=2.0)
        return self.check_now()


def build_train_config(block_size: int = 128, batch_size: int = 4, max_steps: int = 500, **overrides: Any):
    """Build TrainConfig with Budget Lock enforced. Never use TrainConfig() defaults."""
    ok, reason = validate_budget(
        params=int(overrides.get("params", 0)) or 0,
        seq_len=block_size,
        batch_size=batch_size,
        steps=max_steps,
    )
    if not ok:
        raise ValueError(f"budget violated: {reason}")
    if block_size > MAX_SEQ or batch_size > MAX_BATCH or max_steps > MAX_STEPS:
        raise ValueError("budget violated: block_size/batch_size/max_steps exceed Budget Lock")
    from apps.core.native.train import TrainConfig

    kwargs: dict[str, Any] = {"block_size": block_size, "batch_size": batch_size, "max_steps": max_steps}
    kwargs.update({k: v for k, v in overrides.items() if k != "params"})
    return TrainConfig(**kwargs)


@dataclass
class LoopResult:
    status: str
    verdict: str
    reason: str
    evidence: dict[str, Any]


class AutonomousTrainingLoop:
    """Wrapper orchestrator. Does not train by itself."""

    def __init__(
        self,
        checkpoint_dir: str | Path | None = None,
        *,
        loop_timeout_sec: float = MAX_LOOP_TIMEOUT_SECONDS,
        experiment_timeout_sec: float = MAX_EXPERIMENT_TIMEOUT_SECONDS,
        cpu_threads: int = MAX_CPU_THREADS,
        clock: Callable[[], float] = time.monotonic,
        rss_reader: Callable[[], int] = read_rss_bytes,
        disk_usage_fn: Callable[[str | Path], Any] = shutil.disk_usage,
    ):
        if loop_timeout_sec <= 0 or loop_timeout_sec > MAX_LOOP_TIMEOUT_SECONDS:
            raise ValueError(
                f"loop_timeout_sec {loop_timeout_sec} exceeds cap {MAX_LOOP_TIMEOUT_SECONDS}s"
            )
        if experiment_timeout_sec <= 0 or experiment_timeout_sec > MAX_EXPERIMENT_TIMEOUT_SECONDS:
            raise ValueError(
                f"experiment_timeout_sec {experiment_timeout_sec} exceeds cap {MAX_EXPERIMENT_TIMEOUT_SECONDS}s"
            )
        if cpu_threads < 1 or cpu_threads > MAX_CPU_THREADS:
            raise ValueError(f"cpu_threads {cpu_threads} exceeds cap {MAX_CPU_THREADS}")

        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else None
        self.loop_timeout_sec = float(loop_timeout_sec)
        self.experiment_timeout_sec = float(experiment_timeout_sec)
        self.cpu_threads = int(cpu_threads)
        self.clock = clock
        self.rss_reader = rss_reader
        self.disk_usage_fn = disk_usage_fn
        self._loop_started_at: float | None = None

    def start_loop_clock(self) -> float:
        self._loop_started_at = float(self.clock())
        return self._loop_started_at

    def loop_time_remaining(self) -> float:
        if self._loop_started_at is None:
            return self.loop_timeout_sec
        return self.loop_timeout_sec - max(0.0, float(self.clock()) - self._loop_started_at)

    def run_once(
        self,
        ctx: dict[str, Any],
        payload: dict[str, Any],
        *,
        require_tier2: bool = True,
        execute_fn: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
        preflight_fn: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
    ) -> LoopResult:
        if self._loop_started_at is None:
            self.start_loop_clock()

        exp_timeout = float(
            payload.get("experiment_timeout_sec", payload.get("timeout_seconds", self.experiment_timeout_sec))
        )
        loop_timeout = float(payload.get("loop_timeout_sec", self.loop_timeout_sec))
        cpu_threads = int(payload.get("cpu_threads", self.cpu_threads))

        # 0. Loop timeout check before starting experiment
        if self.loop_time_remaining() <= 0:
            return LoopResult(
                status="BLOCKED",
                verdict="BLOCKED",
                reason=f"loop_timeout exceeded ({self.loop_timeout_sec}s)",
                evidence={"stage": "loop_timeout", "error_code": "loop_timeout"},
            )

        # 1. Budget gate — never trust preflight summary for caps.
        ok, reason = validate_budget(
            params=int(payload.get("params", 0) or 0),
            seq_len=int(payload.get("block_size", payload.get("seq_len", 128)) or 128),
            batch_size=int(payload.get("batch_size", 4) or 4),
            steps=int(payload.get("max_steps", payload.get("steps", 500)) or 500),
            cpu_threads=cpu_threads,
            experiment_timeout_sec=exp_timeout,
            loop_timeout_sec=loop_timeout,
        )
        if not ok:
            return LoopResult(
                status="BLOCKED",
                verdict="BLOCKED",
                reason=reason or "budget violated",
                evidence={"stage": "budget", "error_code": "budget_violated"},
            )

        # 2. Preflight — dataset_dir only.
        if preflight_fn is None:
            from apps.core.workflow.handlers.groups import handle_training_preflight as preflight_fn  # type: ignore

        pre = preflight_fn(ctx, payload)
        pre_verdict = getattr(pre, "verdict", "BLOCKED")
        if pre_verdict != "PASS":
            return LoopResult(
                status=map_verdict_to_status(pre_verdict),
                verdict=pre_verdict,
                reason=getattr(pre, "summary", "preflight blocked"),
                evidence={"stage": "preflight", "error_code": getattr(pre, "error_code", None)},
            )

        # 3. Tier-2 approval gate — caller must pass consumed_approval in ctx.
        if require_tier2 and not ctx.get("consumed_approval"):
            return LoopResult(
                status="WAITING_APPROVAL",
                verdict="NOT RUN",
                reason="Tier-2 approval required: no consumed_approval in ctx. Call governance.verify_and_consume() first.",
                evidence={"stage": "approval", "tier": 2},
            )

        # 4. Disk Guard before any checkpoint save.
        ckpt_target = payload.get("checkpoint_dir") or self.checkpoint_dir
        if ckpt_target is not None:
            disk_ok, disk_info = check_disk_reserve(
                ckpt_target,
                reserve_gb=DISK_RESERVE_GB,
                disk_usage_fn=self.disk_usage_fn,
            )
            if not disk_ok:
                return LoopResult(
                    status="WAITING_RESOURCE",
                    verdict="BLOCKED",
                    reason=f"disk reserve violated: free {disk_info['free_gb']} GB < {DISK_RESERVE_GB} GB",
                    evidence={"stage": "disk_guard", "error_code": "disk_reserve_violated", **disk_info},
                )

        # 5. Execute via handler with CPU cap, RuntimeGuard, and RAM monitor around it.
        if execute_fn is None:
            from apps.core.workflow.handlers.groups import handle_training_execute as execute_fn  # type: ignore

        enforce_cpu_thread_cap(cpu_threads)
        runtime_guard = ctx.get("runtime_guard")
        if runtime_guard is None and ckpt_target is not None:
            runtime_guard = TrainingRuntimeGuard(
                ckpt_target,
                experiment_timeout_sec=exp_timeout,
                loop_timeout_sec=loop_timeout,
                loop_started_at=self._loop_started_at,
                cpu_threads=cpu_threads,
                max_new_disk_gb=MAX_NEW_DISK_GB,
                clock=self.clock,
                rss_reader=self.rss_reader,
                disk_usage_fn=self.disk_usage_fn,
                audit_logger=ctx.get("audit"),
                run_id=ctx.get("run_id"),
                step_key=ctx.get("step_key"),
            )

        exec_ctx = dict(ctx)
        if runtime_guard is not None:
            exec_ctx["runtime_guard"] = runtime_guard

        monitor = RamMonitor(rss_reader=self.rss_reader)
        monitor.start()
        try:
            result = execute_fn(exec_ctx, payload)
        finally:
            ram_info = monitor.stop()

        verdict = getattr(result, "verdict", "BLOCKED")
        err_code = getattr(result, "error_code", None)
        if ram_info["exceeded_hard"] or err_code == "ram_hard_limit":
            return LoopResult(
                status="BLOCKED",
                verdict="BLOCKED",
                reason=f"RAM hard stop exceeded: peak {ram_info['peak_gb']} GB >= {RAM_HARD_GB} GB",
                evidence={"stage": "ram_monitor", "error_code": err_code or "ram_hard_stop", **ram_info, "handler_verdict": verdict},
            )
        return LoopResult(
            status=map_verdict_to_status(verdict, error_code=err_code),
            verdict=verdict,
            reason=getattr(result, "summary", ""),
            evidence={
                "stage": "execute",
                "error_code": err_code,
                "ram": ram_info,
                "handler_verdict": verdict,
            },
        )

    def run_experiments(
        self,
        experiments: list[tuple[dict[str, Any], dict[str, Any]]],
        *,
        require_tier2: bool = True,
        execute_fn: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
        preflight_fn: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
    ) -> list[LoopResult]:
        """Execute bounded sequence of experiments until completion or loop_timeout."""
        self.start_loop_clock()
        results: list[LoopResult] = []
        for ctx, payload in experiments:
            if self.loop_time_remaining() <= 0:
                results.append(
                    LoopResult(
                        status="BLOCKED",
                        verdict="BLOCKED",
                        reason=f"loop_timeout exceeded before starting next experiment ({self.loop_timeout_sec}s)",
                        evidence={"stage": "loop_timeout", "error_code": "loop_timeout"},
                    )
                )
                break
            res = self.run_once(
                ctx,
                payload,
                require_tier2=require_tier2,
                execute_fn=execute_fn,
                preflight_fn=preflight_fn,
            )
            results.append(res)
            if res.evidence.get("error_code") in ("loop_timeout", "ram_hard_limit", "ram_hard_stop"):
                break
        return results

