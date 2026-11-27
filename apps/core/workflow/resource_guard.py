"""Resource guard for ZYRQUEN Workflow Engine (RAM, Disk, CPU, and paid-GPU checks)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import time
from typing import Any

GB = 1024 ** 3
MAX_CPU_THREADS = 2
RAM_SOFT_LIMIT_GB = 3.0
RAM_HARD_LIMIT_GB = 3.5
MIN_DISK_RESERVE_GB = 2.0
MAX_NEW_DISK_GB = 1.0
MAX_CPU_TRAINING_STEPS = 1000
MAX_V10_STEPS = 500
MAX_CPU_MODEL_PARAMETERS = 5_000_000
MAX_CPU_BATCH_SIZE = 4
MAX_CPU_SEQUENCE_LENGTH = 256
MAX_EXPERIMENT_TIMEOUT_SECONDS = 3600
MAX_LOOP_TIMEOUT_SECONDS = 14400


def _coerce_params_count(value: Any) -> int | None:
    """Strictly coerce an estimated parameter count; None means not a non-negative integer."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        return int(text) if text.isdigit() else None
    return None


def enforce_cpu_thread_cap(
    max_threads: int = MAX_CPU_THREADS,
    torch_mod: Any | None = None,
) -> dict[str, Any]:
    """Cap BLAS/OpenMP and PyTorch thread counts to prevent CPU oversubscription."""
    if isinstance(max_threads, bool):
        raise ValueError("max_threads must be an integer")
    cap = int(max_threads)
    if cap < 1 or cap > MAX_CPU_THREADS:
        raise ValueError(
            f"cpu_threads {cap} out of allowed bounds [1, {MAX_CPU_THREADS}]"
        )
    cap_str = str(cap)
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "TORCH_NUM_THREADS",
    ):
        os.environ[var] = cap_str

    torch_threads: int | None = None
    interop_threads: int | None = None
    interop_note = ""
    try:
        mod = torch_mod
        if mod is None:
            import torch as mod  # type: ignore

        mod.set_num_threads(cap)
        torch_threads = int(mod.get_num_threads())
        try:
            current_interop = int(mod.get_num_interop_threads())
            mod.set_num_interop_threads(min(cap, max(1, current_interop)))
            interop_threads = int(mod.get_num_interop_threads())
        except Exception as exc:
            interop_note = str(exc)
    except Exception:
        pass

    return {
        "cap": cap,
        "torch_threads": torch_threads,
        "interop_threads": interop_threads,
        "interop_note": interop_note,
    }


def read_process_rss_bytes(pid: int | None = None) -> int:
    """Return current process RSS in bytes (best-effort across Linux/Colab)."""
    target_pid = os.getpid() if pid is None else int(pid)
    status_path = Path(f"/proc/{target_pid}/status")
    if status_path.exists():
        try:
            for line in status_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
        except Exception:
            pass
    try:
        import resource

        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(rss_kb) * 1024
    except Exception:
        return 0


def check_disk_reserve(
    path: str | Path = ".",
    reserve_gb: float = MIN_DISK_RESERVE_GB,
    *,
    disk_usage_fn: Callable[[Any], Any] = shutil.disk_usage,
) -> tuple[bool, dict[str, Any]]:
    """Check free disk space against required reserve_gb and return (ok, info)."""
    target = Path(path)
    probe_path = target if target.exists() else target.parent
    if not probe_path.exists():
        probe_path = Path(".")
    usage = disk_usage_fn(probe_path)
    free_gb = usage.free / GB
    total_gb = usage.total / GB
    ok = free_gb >= float(reserve_gb)
    info = {
        "ok": ok,
        "path": str(probe_path.resolve()),
        "free_gb": round(free_gb, 4),
        "total_gb": round(total_gb, 4),
        "reserve_gb": float(reserve_gb),
    }
    return ok, info


def check_torch_cpu_runtime(max_threads: int = MAX_CPU_THREADS) -> dict[str, Any]:
    """Verify PyTorch runtime availability and CPU thread settings honestly."""
    enforce_cpu_thread_cap(max_threads)
    info: dict[str, Any] = {
        "ok": True,
        "status": "TORCH_NOT_INSTALLED",
        "available": False,
        "torch_available": False,
        "cuda_available": False,
        "max_threads": int(max_threads),
        "num_threads": None,
    }
    try:
        import torch  # type: ignore

        info["status"] = "TORCH_AVAILABLE"
        info["available"] = True
        info["torch_available"] = True
        info["cuda_available"] = bool(torch.cuda.is_available())
        info["num_threads"] = int(torch.get_num_threads())
        if info["num_threads"] > int(max_threads):
            info["ok"] = False
    except Exception as exc:
        info["ok"] = False
        info["error"] = str(exc)
    return info


def _directory_size_bytes(directory: Path) -> int:
    if not directory.exists() or not directory.is_dir():
        return 0
    total = 0
    for root, _, files in os.walk(directory):
        for fname in files:
            fpath = Path(root) / fname
            if fpath.is_symlink():
                continue
            try:
                total += fpath.stat().st_size
            except OSError:
                continue
    return total


class TrainingRuntimeGuard:
    """Runtime guard for training loops checking timeouts, RSS RAM, disk reserve, and new disk budget."""

    def __init__(
        self,
        work_dir: str | Path = ".",
        *,
        min_free_disk_gb: float = MIN_DISK_RESERVE_GB,
        ram_soft_limit_gb: float = RAM_SOFT_LIMIT_GB,
        ram_hard_limit_gb: float = RAM_HARD_LIMIT_GB,
        max_new_disk_gb: float = MAX_NEW_DISK_GB,
        experiment_timeout_sec: float = 1200.0,
        loop_timeout_sec: float = 3600.0,
        loop_started_at: float | None = None,
        cpu_threads: int = MAX_CPU_THREADS,
        clock: Callable[[], float] = time.monotonic,
        rss_reader: Callable[[], int] = read_process_rss_bytes,
        disk_usage_fn: Callable[[Any], Any] = shutil.disk_usage,
        audit_logger: Any = None,
        run_id: str | None = None,
        step_key: str | None = None,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.min_free_disk_gb = float(min_free_disk_gb)
        self.ram_soft_limit_gb = float(ram_soft_limit_gb)
        self.ram_hard_limit_gb = float(ram_hard_limit_gb)
        self.max_new_disk_gb = float(max_new_disk_gb)
        self.experiment_timeout_sec = float(experiment_timeout_sec)
        self.loop_timeout_sec = float(loop_timeout_sec)
        self.loop_started_at = loop_started_at
        self.cpu_threads = int(cpu_threads)
        self.clock = clock
        self.rss_reader = rss_reader
        self.disk_usage_fn = disk_usage_fn
        self.audit_logger = audit_logger
        self.run_id = run_id
        self.step_key = step_key
        self._exp_started_at: float | None = None
        self._baseline_bytes: int = _directory_size_bytes(self.work_dir)
        self._soft_warned = False

    def start(self) -> TrainingRuntimeGuard:
        self._exp_started_at = float(self.clock())
        if self.loop_started_at is None:
            self.loop_started_at = self._exp_started_at
        self._baseline_bytes = _directory_size_bytes(self.work_dir)
        return self

    def _emit_audit(self, event_type: str, decision: str, details: dict[str, Any]) -> None:
        if self.audit_logger is None or not hasattr(self.audit_logger, "record"):
            return
        try:
            self.audit_logger.record(
                actor_id="system:runtime_guard",
                event_type=event_type,
                resource=f"work_dir:{self.work_dir}",
                decision=decision,
                details=details,
                run_id=self.run_id,
                step_key=self.step_key,
            )
        except Exception:
            pass

    def check_runtime(
        self,
        phase: str = "step",
        *,
        step: int | None = None,
        checkpoint_write: bool = False,
    ) -> tuple[bool, str | None, dict[str, Any]]:
        now = float(self.clock())
        exp_elapsed = (now - self._exp_started_at) if self._exp_started_at is not None else 0.0
        loop_elapsed = (now - self.loop_started_at) if self.loop_started_at is not None else 0.0

        rss_bytes = int(self.rss_reader() or 0)
        rss_gb = rss_bytes / GB

        disk_ok, disk_info = check_disk_reserve(
            self.work_dir,
            reserve_gb=self.min_free_disk_gb,
            disk_usage_fn=self.disk_usage_fn,
        )
        current_bytes = _directory_size_bytes(self.work_dir)
        new_bytes = max(0, current_bytes - self._baseline_bytes)
        new_disk_gb = new_bytes / GB

        soft_warning_triggered = rss_gb >= self.ram_soft_limit_gb
        snap: dict[str, Any] = {
            "phase": phase,
            "step": step,
            "checkpoint_write": bool(checkpoint_write),
            "rss_gb": round(rss_gb, 4),
            "soft_warning_triggered": soft_warning_triggered,
            "free_disk_gb": disk_info["free_gb"],
            "new_disk_gb": round(new_disk_gb, 6),
            "exp_elapsed_sec": round(exp_elapsed, 3),
            "loop_elapsed_sec": round(loop_elapsed, 3),
        }

        if self._exp_started_at is not None and exp_elapsed > self.experiment_timeout_sec:
            self._emit_audit("training.experiment_timeout", "BLOCKED", snap)
            return False, "experiment_timeout", snap

        if self.loop_started_at is not None and loop_elapsed > self.loop_timeout_sec:
            self._emit_audit("training.loop_timeout", "BLOCKED", snap)
            return False, "loop_timeout", snap

        if rss_gb >= self.ram_hard_limit_gb:
            self._emit_audit("training.ram_hard_limit", "BLOCKED", snap)
            return False, "ram_hard_limit", snap

        if soft_warning_triggered and not self._soft_warned:
            self._soft_warned = True
            self._emit_audit("training.ram_soft_warning", "WARN", snap)

        if not disk_ok:
            self._emit_audit("training.disk_reserve_violated", "BLOCKED", snap)
            return False, "disk_reserve_violated", snap

        if new_disk_gb > self.max_new_disk_gb:
            self._emit_audit("training.disk_budget_violated", "BLOCKED", snap)
            return False, "disk_budget_violated", snap

        return True, None, snap


@dataclass
class GuardOutcome:
    allowed: bool
    blocked: bool = False
    reason: str = "ok"
    detail: Any = None

    @property
    def wait_for_resource(self) -> bool:
        if isinstance(self.detail, dict) and "wait_for_resource" in self.detail:
            return bool(self.detail["wait_for_resource"])
        return bool((not self.allowed) and (not self.blocked))

    @property
    def snapshot(self) -> dict[str, Any]:
        if isinstance(self.detail, dict):
            return self.detail
        if self.detail is None:
            return {"allowed": self.allowed, "blocked": self.blocked, "reason": self.reason}
        return {"detail": self.detail}


@dataclass
class WorkflowResourceGuard:
    """Guards workflow execution against RAM, disk reserve, CPU, and unapproved paid GPU."""

    work_dir: str | Path = "."
    min_free_disk_gb: float = MIN_DISK_RESERVE_GB
    ram_hard_limit_gb: float = RAM_HARD_LIMIT_GB
    max_cpu_threads: int = MAX_CPU_THREADS
    resource_manager: Any = None
    _disk_usage_fn: Callable[[Any], Any] = field(default=shutil.disk_usage, repr=False)

    def __post_init__(self) -> None:
        if self.resource_manager is not None:
            max_ram_mb = getattr(self.resource_manager, "max_ram_mb", None)
            if isinstance(max_ram_mb, (int, float)) and max_ram_mb > 0:
                self.ram_hard_limit_gb = float(max_ram_mb) / 1024.0

    def snapshot(self) -> dict[str, Any]:
        rss_bytes = read_process_rss_bytes()
        rss_mb = round(rss_bytes / (1024 * 1024), 2)
        disk_ok, disk = check_disk_reserve(
            self.work_dir,
            reserve_gb=self.min_free_disk_gb,
            disk_usage_fn=self._disk_usage_fn,
        )
        vram_available = False
        try:
            import torch  # type: ignore

            vram_available = bool(torch.cuda.is_available())
        except Exception:
            vram_available = False
        return {
            "ram_mb": rss_mb,
            "rss_gb": round(rss_bytes / GB, 4),
            "free_disk_gb": disk["free_gb"],
            "disk_ok": disk_ok,
            "vram_available": vram_available,
            "max_cpu_threads": self.max_cpu_threads,
        }

    def check_step(
        self,
        step: Any = None,
        payload: dict[str, Any] | None = None,
        *,
        use_paid_gpu: bool = False,
        has_paid_gpu_approval: bool = False,
        steps: int | None = None,
        estimated_params: int | None = None,
        **_: Any,
    ) -> GuardOutcome:
        payload = payload or {}
        snap = self.snapshot()

        step_requires_gpu = bool(getattr(step, "requires_paid_gpu", False)) if step is not None else False
        paid_gpu = bool(use_paid_gpu or step_requires_gpu or payload.get("use_paid_gpu", False))
        if paid_gpu and not has_paid_gpu_approval:
            return GuardOutcome(
                allowed=False,
                blocked=True,
                reason="Paid cloud GPU compute is blocked without Tier-2 approval.",
                detail={**snap, "detail": "Paid GPU requested without approval."},
            )

        cpu_threads_raw = payload.get("cpu_threads")
        if cpu_threads_raw is not None:
            if isinstance(cpu_threads_raw, bool) or not isinstance(cpu_threads_raw, (int, float)):
                return GuardOutcome(
                    allowed=False,
                    blocked=True,
                    reason="invalid_cpu_threads",
                    detail={**snap, "cpu_threads": cpu_threads_raw, "max_cpu_threads": self.max_cpu_threads},
                )
            cpu_threads_val = int(cpu_threads_raw)
            if cpu_threads_val < 1 or cpu_threads_val > self.max_cpu_threads:
                return GuardOutcome(
                    allowed=False,
                    blocked=True,
                    reason=f"cpu_threads {cpu_threads_val} exceeds cap {self.max_cpu_threads}",
                    detail={**snap, "cpu_threads": cpu_threads_val, "max_cpu_threads": self.max_cpu_threads},
                )

        min_step_disk = float(getattr(step, "min_disk_gb", self.min_free_disk_gb) or self.min_free_disk_gb)
        effective_disk_reserve = max(self.min_free_disk_gb, min_step_disk) if step_requires_gpu else self.min_free_disk_gb
        free_disk_gb = float(snap.get("free_disk_gb", 0.0))
        if free_disk_gb < effective_disk_reserve:
            return GuardOutcome(
                allowed=False,
                blocked=True,
                reason="disk_reserve_violated",
                detail=snap,
            )

        ram_mb = float(snap.get("ram_mb", 0.0))
        if ram_mb > self.ram_hard_limit_gb * 1024.0:
            return GuardOutcome(
                allowed=False,
                blocked=True,
                reason="ram_hard_limit",
                detail={**snap, "hard_limit_gb": self.ram_hard_limit_gb},
            )

        is_preflight_readonly = (
            step is not None
            and getattr(step, "action_type", "") == "read_only"
            and getattr(step, "step_key", "") in ("preflight", "ingest_dataset")
            and getattr(step, "lane", "") != "compute_heavy"
        )
        step_count = (
            steps
            if steps is not None
            else (None if is_preflight_readonly else payload.get("steps", payload.get("max_steps")))
        )
        if step_count is not None and not isinstance(step_count, bool) and int(step_count) > MAX_CPU_TRAINING_STEPS:
            return GuardOutcome(
                allowed=False,
                blocked=True,
                reason="step_limit_exceeded",
                detail={**snap, "steps": int(step_count), "max_steps": MAX_CPU_TRAINING_STEPS},
            )

        params_count = (
            estimated_params
            if estimated_params is not None
            else (None if is_preflight_readonly else payload.get("estimated_params"))
        )
        if params_count is not None:
            params_count = _coerce_params_count(params_count)
            if params_count is None:
                return GuardOutcome(
                    allowed=False,
                    blocked=True,
                    reason="invalid_estimated_params",
                    detail={**snap, "max_params": MAX_CPU_MODEL_PARAMETERS},
                )
            if params_count > MAX_CPU_MODEL_PARAMETERS:
                return GuardOutcome(
                    allowed=False,
                    blocked=True,
                    reason="parameter_budget_exceeded",
                    detail={**snap, "estimated_params": params_count, "max_params": MAX_CPU_MODEL_PARAMETERS},
                )

        return GuardOutcome(
            allowed=True,
            blocked=False,
            reason="ok",
            detail=snap,
        )
