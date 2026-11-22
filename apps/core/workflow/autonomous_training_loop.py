"""Autonomous Training Loop — Wrapper only.

No new Trainer / Registry / Approval Gate / Resource Guard.
Reuses: handlers.groups, governance, resource_guard,
native.train.TrainConfig, native.checkpoint.VersionedCheckpointManager.

Evidence-locked facts:
- handle_training_execute routes to TrainingOrchestrator (SFT or token-stream LM)
  only after Tier-2 HMAC approval and returns NOT RUN / BLOCKED when torch or
  configuration prerequisites are unavailable; wrapper must propagate NOT RUN / BLOCKED
  and never claim COMPLETED falsely.
- TrainConfig defaults (batch=16, max_steps=1000) violate Budget Lock.
  Wrapper must override to batch<=4, steps<=500, block_size<=256.
- handle_training_preflight only checks dataset_dir, not caps.
  Wrapper must enforce budget itself.
- TrainingMonitor is a file logger (log/history/summary), not a RAM monitor.
  Wrapper uses a lightweight RSS poller around the handler call.
- VersionedCheckpointManager.save_versioned is keyword-only and rejects
  duplicate model_version. Disk Guard runs before it.
"""
from __future__ import annotations

import os
import resource
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Resource Budget Lock — stricter than resource_guard on steps
MAX_PARAMS = 5_000_000
MAX_SEQ = 256
MAX_BATCH = 4
MAX_STEPS = 500
RAM_SOFT_GB = 3.0
RAM_HARD_GB = 3.5
DISK_RESERVE_GB = 2.0
MAX_CHECKPOINTS_PER_RUN = 10
GB = 1024 * 1024 * 1024

def map_verdict_to_status(verdict: str) -> str:
    """Implementation A mapping: PASS->COMPLETED, NOT RUN/BLOCKED->BLOCKED, FAIL->FAILED."""
    if verdict == "PASS":
        return "COMPLETED"
    if verdict in ("NOT RUN", "BLOCKED"):
        return "BLOCKED"
    if verdict == "FAIL":
        return "FAILED"
    return "BLOCKED"

def validate_budget(params: int, seq_len: int, batch_size: int, steps: int) -> tuple[bool, str | None]:
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
    return True, None

def check_disk_reserve(checkpoint_dir: str | Path, reserve_gb: float = DISK_RESERVE_GB) -> tuple[bool, dict[str, Any]]:
    p = Path(checkpoint_dir)
    try:
        usage = shutil.disk_usage(str(p if p.exists() else p.parent if str(p.parent) else "."))
    except FileNotFoundError:
        usage = shutil.disk_usage(".")
    free_gb = usage.free / GB
    ok = free_gb >= reserve_gb
    return ok, {"free_gb": round(free_gb, 3), "reserve_gb": reserve_gb, "ok": ok}

def read_rss_bytes() -> int:
    # Linux: ru_maxrss is KB. Fallback to /proc/self/status VmRSS.
    try:
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except Exception:
        pass
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except Exception:
        pass
    return 0

class RamMonitor(threading.Thread):
    """Lightweight RSS poller. Runs around handle_training_execute, not inside train()."""

    def __init__(self, interval_s: float = 0.5):
        super().__init__(daemon=True)
        self.interval_s = interval_s
        self.peak_bytes = 0
        self.exceeded_soft = False
        self.exceeded_hard = False
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            rss = read_rss_bytes()
            if rss > self.peak_bytes:
                self.peak_bytes = rss
            if rss >= RAM_SOFT_GB * GB:
                self.exceeded_soft = True
            if rss >= RAM_HARD_GB * GB:
                self.exceeded_hard = True
                break
            self._stop_event.wait(self.interval_s)

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        self.join(timeout=2.0)
        return {
            "peak_gb": round(self.peak_bytes / GB, 3),
            "exceeded_soft": self.exceeded_soft,
            "exceeded_hard": self.exceeded_hard,
        }

def build_train_config(block_size: int = 128, batch_size: int = 4, max_steps: int = 500, **overrides: Any):
    """Build TrainConfig with Budget Lock enforced. Never use TrainConfig() defaults."""
    ok, reason = validate_budget(
        params=int(overrides.get("params", 0)) or 0,
        seq_len=block_size,
        batch_size=batch_size,
        steps=max_steps,
    )
    # params=0 means caller did not supply params; only enforce seq/batch/steps here.
    # Full params check happens in validate_budget caller with real model size.
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

    def __init__(self, checkpoint_dir: str | Path | None = None):
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else None

    def run_once(
        self,
        ctx: dict[str, Any],
        payload: dict[str, Any],
        *,
        require_tier2: bool = True,
        execute_fn: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
        preflight_fn: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
    ) -> LoopResult:
        # 1. Budget gate — never trust preflight summary for caps.
        ok, reason = validate_budget(
            params=int(payload.get("params", 0) or 0),
            seq_len=int(payload.get("block_size", payload.get("seq_len", 128)) or 128),
            batch_size=int(payload.get("batch_size", 4) or 4),
            steps=int(payload.get("max_steps", payload.get("steps", 500)) or 500),
        )
        # params==0 means payload did not declare model size; skip params check, enforce rest.
        if not ok:
            return LoopResult(status="BLOCKED", verdict="BLOCKED", reason=reason or "budget violated", evidence={"stage": "budget"})

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
        # Wrapper never invents approval. If required and missing -> WAITING_APPROVAL.
        if require_tier2 and not ctx.get("consumed_approval"):
            return LoopResult(
                status="WAITING_APPROVAL",
                verdict="NOT RUN",
                reason="Tier-2 approval required: no consumed_approval in ctx. Call governance.verify_and_consume() first.",
                evidence={"stage": "approval", "tier": 2},
            )

        # 4. Disk Guard before any checkpoint save.
        if self.checkpoint_dir is not None:
            disk_ok, disk_info = check_disk_reserve(self.checkpoint_dir)
            if not disk_ok:
                return LoopResult(
                    status="BLOCKED",
                    verdict="BLOCKED",
                    reason=f"disk reserve violated: free {disk_info['free_gb']} GB < {DISK_RESERVE_GB} GB",
                    evidence={"stage": "disk_guard", **disk_info},
                )

        # 5. Execute via handler with RAM monitor around it (propagates NOT RUN/BLOCKED honestly).
        if execute_fn is None:
            from apps.core.workflow.handlers.groups import handle_training_execute as execute_fn  # type: ignore

        monitor = RamMonitor()
        monitor.start()
        try:
            result = execute_fn(ctx, payload)
        finally:
            ram_info = monitor.stop()

        verdict = getattr(result, "verdict", "BLOCKED")
        if ram_info["exceeded_hard"]:
            return LoopResult(
                status="BLOCKED",
                verdict="BLOCKED",
                reason=f"RAM hard stop exceeded: peak {ram_info['peak_gb']} GB >= {RAM_HARD_GB} GB",
                evidence={"stage": "ram_monitor", **ram_info, "handler_verdict": verdict},
            )
        return LoopResult(
            status=map_verdict_to_status(verdict),
            verdict=verdict,
            reason=getattr(result, "summary", ""),
            evidence={
                "stage": "execute",
                "error_code": getattr(result, "error_code", None),
                "ram": ram_info,
                "handler_verdict": verdict,
            },
        )
