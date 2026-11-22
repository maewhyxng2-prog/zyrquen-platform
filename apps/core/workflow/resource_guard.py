"""Unified CPU / RAM / GPU / Disk and CostLimits Resource Guard for Workflow Engine."""

from __future__ import annotations

import importlib.util
import os
import resource
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from apps.core.resource import ResourceManager
from apps.core.training.cost_limits import cost_controller_from_env
from apps.core.training_infrastructure.cost.cost_controller import CostController, CostLimits
from apps.core.workflow.models import WorkflowStepSpec


GB = 1024 * 1024 * 1024
MAX_CPU_THREADS = 2
MAX_CPU_MODEL_PARAMETERS = 5_000_000
MAX_CPU_SEQUENCE_LENGTH = 256
MAX_CPU_BATCH_SIZE = 4
MAX_CPU_TRAINING_STEPS = 500
MAX_EXPERIMENT_TIMEOUT_SECONDS = 1200.0
MAX_LOOP_TIMEOUT_SECONDS = 3600.0
RAM_SOFT_LIMIT_GB = 3.0
RAM_HARD_LIMIT_GB = 3.5
MIN_DISK_RESERVE_GB = 2.0
MAX_NEW_DISK_GB = 1.0

_THREAD_ENV_KEYS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "TORCH_NUM_THREADS",
)


def read_process_rss_bytes() -> int:
    """Return process RSS in bytes from /proc/self/status or resource.getrusage."""
    vm_rss = 0
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                vm_rss = int(line.split()[1]) * 1024
                break
    except Exception:
        vm_rss = 0
    if vm_rss > 0:
        return vm_rss
    try:
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except Exception:
        return 0


def measure_dir_bytes(target_dir: str | Path) -> int:
    root = Path(target_dir)
    if not root.exists():
        return 0
    total = 0
    for item in root.rglob("*"):
        if item.is_file() and not item.is_symlink():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def check_disk_reserve(
    target_dir: str | Path,
    reserve_gb: float = MIN_DISK_RESERVE_GB,
    *,
    disk_usage_fn: Callable[[str | Path], Any] = shutil.disk_usage,
) -> tuple[bool, dict[str, Any]]:
    p = Path(target_dir)
    probe = p if p.exists() else (p.parent if p.parent.exists() else Path("."))
    try:
        usage = disk_usage_fn(str(probe))
    except FileNotFoundError:
        usage = disk_usage_fn(".")
    free_gb = usage.free / GB
    ok = free_gb >= float(reserve_gb)
    return ok, {"free_gb": round(free_gb, 3), "reserve_gb": float(reserve_gb), "ok": ok}


def check_torch_cpu_runtime() -> dict[str, Any]:
    """Read-only probe for PyTorch CPU installation status without mutating environment."""
    if importlib.util.find_spec("torch") is None:
        return {
            "available": False,
            "status": "TORCH_NOT_INSTALLED",
            "version": None,
            "cuda_available": False,
        }
    import torch

    cuda_avail = False
    try:
        cuda_avail = bool(torch.cuda.is_available())
    except Exception:
        cuda_avail = False
    return {
        "available": True,
        "status": "TORCH_AVAILABLE",
        "version": getattr(torch, "__version__", None),
        "cuda_available": cuda_avail,
    }


def enforce_cpu_thread_cap(
    max_threads: int = MAX_CPU_THREADS,
    *,
    torch_mod: Any | None = None,
) -> dict[str, Any]:
    """Enforce CPU thread cap across BLAS/OpenMP env vars and PyTorch intra/interop pools."""
    if max_threads < 1 or max_threads > MAX_CPU_THREADS:
        raise ValueError(
            f"cpu_threads {max_threads} violates CPU thread cap (1 <= cpu_threads <= {MAX_CPU_THREADS})"
        )
    cap = int(max_threads)
    cap_str = str(cap)
    for key in _THREAD_ENV_KEYS:
        os.environ[key] = cap_str

    torch_obj = torch_mod
    if torch_obj is None and importlib.util.find_spec("torch") is not None:
        import torch as torch_obj  # type: ignore

    torch_threads: int | None = None
    torch_interop: int | None = None
    interop_note: str | None = None

    if torch_obj is not None:
        if hasattr(torch_obj, "set_num_threads"):
            torch_obj.set_num_threads(cap)
        if hasattr(torch_obj, "set_num_interop_threads"):
            try:
                torch_obj.set_num_interop_threads(cap)
            except RuntimeError as exc:
                interop_note = str(exc)
        if hasattr(torch_obj, "get_num_threads"):
            torch_threads = int(torch_obj.get_num_threads())
            if torch_threads > cap:
                raise RuntimeError(f"Failed to enforce torch num_threads <= {cap}: got {torch_threads}")
        if hasattr(torch_obj, "get_num_interop_threads"):
            torch_interop = int(torch_obj.get_num_interop_threads())

    return {
        "cap": cap,
        "env": {key: os.environ.get(key) for key in _THREAD_ENV_KEYS},
        "torch_threads": torch_threads,
        "torch_interop_threads": torch_interop,
        "interop_note": interop_note,
    }


class TrainingRuntimeGuard:
    """Enforces experiment/loop timeouts, RAM soft/hard caps, disk reserve, and new-disk cap during training."""

    def __init__(
        self,
        checkpoint_dir: str | Path,
        *,
        experiment_timeout_sec: float = MAX_EXPERIMENT_TIMEOUT_SECONDS,
        loop_timeout_sec: float = MAX_LOOP_TIMEOUT_SECONDS,
        loop_started_at: float | None = None,
        ram_soft_gb: float = RAM_SOFT_LIMIT_GB,
        ram_hard_gb: float = RAM_HARD_LIMIT_GB,
        disk_reserve_gb: float = MIN_DISK_RESERVE_GB,
        max_new_disk_gb: float = MAX_NEW_DISK_GB,
        cpu_threads: int = MAX_CPU_THREADS,
        clock: Callable[[], float] = time.monotonic,
        rss_reader: Callable[[], int] = read_process_rss_bytes,
        disk_usage_fn: Callable[[str | Path], Any] = shutil.disk_usage,
        audit_logger: Any | None = None,
        run_id: str | None = None,
        step_key: str | None = None,
    ) -> None:
        if experiment_timeout_sec <= 0 or experiment_timeout_sec > MAX_EXPERIMENT_TIMEOUT_SECONDS:
            raise ValueError(
                f"experiment_timeout_sec {experiment_timeout_sec} exceeds cap {MAX_EXPERIMENT_TIMEOUT_SECONDS}s"
            )
        if loop_timeout_sec <= 0 or loop_timeout_sec > MAX_LOOP_TIMEOUT_SECONDS:
            raise ValueError(
                f"loop_timeout_sec {loop_timeout_sec} exceeds cap {MAX_LOOP_TIMEOUT_SECONDS}s"
            )
        if ram_soft_gb <= 0 or ram_soft_gb > RAM_SOFT_LIMIT_GB:
            raise ValueError(f"ram_soft_gb {ram_soft_gb} exceeds cap {RAM_SOFT_LIMIT_GB} GB")
        if ram_hard_gb <= 0 or ram_hard_gb > RAM_HARD_LIMIT_GB:
            raise ValueError(f"ram_hard_gb {ram_hard_gb} exceeds cap {RAM_HARD_LIMIT_GB} GB")
        if ram_soft_gb > ram_hard_gb:
            raise ValueError("ram_soft_gb must be <= ram_hard_gb")
        if disk_reserve_gb < MIN_DISK_RESERVE_GB:
            raise ValueError(
                f"disk_reserve_gb {disk_reserve_gb} below mandatory floor {MIN_DISK_RESERVE_GB} GB"
            )
        if max_new_disk_gb <= 0 or max_new_disk_gb > MAX_NEW_DISK_GB:
            raise ValueError(f"max_new_disk_gb {max_new_disk_gb} exceeds cap {MAX_NEW_DISK_GB} GB")
        if cpu_threads < 1 or cpu_threads > MAX_CPU_THREADS:
            raise ValueError(f"cpu_threads {cpu_threads} exceeds cap {MAX_CPU_THREADS}")

        self.checkpoint_dir = Path(checkpoint_dir)
        self.experiment_timeout_sec = float(experiment_timeout_sec)
        self.loop_timeout_sec = float(loop_timeout_sec)
        self.clock = clock
        self.loop_started_at = float(loop_started_at) if loop_started_at is not None else float(clock())
        self.ram_soft_gb = float(ram_soft_gb)
        self.ram_hard_gb = float(ram_hard_gb)
        self.disk_reserve_gb = float(disk_reserve_gb)
        self.max_new_disk_gb = float(max_new_disk_gb)
        self.cpu_threads = int(cpu_threads)
        self.rss_reader = rss_reader
        self.disk_usage_fn = disk_usage_fn
        self.audit_logger = audit_logger
        self.run_id = run_id
        self.step_key = step_key

        self.cost_controller = CostController(
            CostLimits(hourly_rate_usd=0.0, max_runtime_seconds=self.experiment_timeout_sec),
            clock=self.clock,
        )
        self._baseline_disk_bytes = measure_dir_bytes(self.checkpoint_dir)
        self.peak_rss_bytes = 0
        self.soft_warning_triggered = False
        self.soft_warning_logged = False
        self.hard_stop_reason: str | None = None
        self.started = False

    def start(self) -> None:
        if not self.started:
            self.cost_controller.start()
            self.started = True

    def pause(self) -> None:
        self.cost_controller.pause()

    def _audit(self, event_type: str, decision: str, details: dict[str, Any]) -> None:
        if self.audit_logger is None:
            return
        try:
            self.audit_logger.record(
                actor_id="system:resource_guard",
                event_type=event_type,
                resource=f"training:{self.checkpoint_dir}",
                decision=decision,
                details=details,
                run_id=self.run_id,
                step_key=self.step_key,
            )
        except Exception:
            pass

    def snapshot(self) -> dict[str, Any]:
        rss_bytes = int(self.rss_reader() or 0)
        if rss_bytes > self.peak_rss_bytes:
            self.peak_rss_bytes = rss_bytes
        _, disk_info = check_disk_reserve(
            self.checkpoint_dir,
            reserve_gb=self.disk_reserve_gb,
            disk_usage_fn=self.disk_usage_fn,
        )
        current_dir_bytes = measure_dir_bytes(self.checkpoint_dir)
        new_disk_bytes = max(0, current_dir_bytes - self._baseline_disk_bytes)
        now = float(self.clock())
        return {
            "elapsed_experiment_sec": round(self.cost_controller.elapsed_seconds(), 4),
            "experiment_timeout_sec": self.experiment_timeout_sec,
            "elapsed_loop_sec": round(max(0.0, now - self.loop_started_at), 4),
            "loop_timeout_sec": self.loop_timeout_sec,
            "rss_gb": round(rss_bytes / GB, 4),
            "peak_rss_gb": round(self.peak_rss_bytes / GB, 4),
            "soft_warning_triggered": self.soft_warning_triggered,
            "free_disk_gb": disk_info["free_gb"],
            "disk_reserve_gb": self.disk_reserve_gb,
            "new_disk_gb": round(new_disk_bytes / GB, 4),
            "max_new_disk_gb": self.max_new_disk_gb,
            "cpu_threads": self.cpu_threads,
        }

    def check_runtime(
        self,
        stage: str,
        *,
        step: int | None = None,
        checkpoint_write: bool = False,
    ) -> tuple[bool, str | None, dict[str, Any]]:
        snap = self.snapshot()

        if snap["elapsed_loop_sec"] >= self.loop_timeout_sec:
            self.hard_stop_reason = "loop_timeout"
            self._audit(
                "training.loop_timeout",
                "BLOCKED",
                {"stage": stage, "step": step, **snap},
            )
            return False, "loop_timeout", snap

        cost_exceeded = self.cost_controller.exceeded()
        if cost_exceeded is not None:
            reason = "experiment_timeout" if cost_exceeded == "max_runtime_seconds" else str(cost_exceeded)
            self.hard_stop_reason = reason
            self._audit(
                "training.experiment_timeout",
                "BLOCKED",
                {"stage": stage, "step": step, "cost_reason": cost_exceeded, **snap},
            )
            return False, reason, snap

        if snap["rss_gb"] >= self.ram_hard_gb:
            self.hard_stop_reason = "ram_hard_limit"
            self._audit(
                "training.ram_hard_limit",
                "BLOCKED",
                {"stage": stage, "step": step, **snap},
            )
            return False, "ram_hard_limit", snap

        if snap["rss_gb"] >= self.ram_soft_gb:
            self.soft_warning_triggered = True
            snap["soft_warning_triggered"] = True
            if not self.soft_warning_logged:
                self.soft_warning_logged = True
                self._audit(
                    "training.ram_soft_warning",
                    "WARN",
                    {"stage": stage, "step": step, **snap},
                )

        if snap["free_disk_gb"] < self.disk_reserve_gb:
            self.hard_stop_reason = "disk_reserve_violated"
            self._audit(
                "training.disk_reserve_violated",
                "BLOCKED" if checkpoint_write else "WAITING_RESOURCE",
                {"stage": stage, "step": step, "checkpoint_write": checkpoint_write, **snap},
            )
            return False, "disk_reserve_violated", snap

        if snap["new_disk_gb"] > self.max_new_disk_gb:
            self.hard_stop_reason = "disk_budget_violated"
            self._audit(
                "training.disk_budget_violated",
                "BLOCKED",
                {"stage": stage, "step": step, "checkpoint_write": checkpoint_write, **snap},
            )
            return False, "disk_budget_violated", snap

        return True, None, snap


@dataclass(frozen=True)
class ResourceCheckOutcome:
    allowed: bool
    reason: str
    wait_for_resource: bool
    blocked: bool
    snapshot: dict[str, Any]


class WorkflowResourceGuard:
    def __init__(
        self,
        *,
        resource_manager: ResourceManager | None = None,
        work_dir: str | Path = ".",
        min_free_disk_gb: float = MIN_DISK_RESERVE_GB,
    ) -> None:
        self.resource_manager = resource_manager or ResourceManager()
        self.work_dir = Path(work_dir)
        self.min_free_disk_gb = float(min_free_disk_gb)

    def snapshot(self) -> dict[str, Any]:
        snap = self.resource_manager.snapshot()
        target = self.work_dir if self.work_dir.exists() else Path(".")
        disk = shutil.disk_usage(target)
        load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
        return {
            **snap,
            "cpu_count": os.cpu_count() or 1,
            "load_1m": round(load_avg[0], 3),
            "free_disk_gb": round(disk.free / GB, 3),
            "total_disk_gb": round(disk.total / GB, 3),
            "cpu_thread_cap": MAX_CPU_THREADS,
            "ram_soft_limit_gb": RAM_SOFT_LIMIT_GB,
            "ram_hard_limit_gb": RAM_HARD_LIMIT_GB,
            "disk_reserve_gb": self.min_free_disk_gb,
        }

    def check_step(
        self,
        step: WorkflowStepSpec,
        payload: dict[str, Any],
        *,
        has_paid_gpu_approval: bool = False,
    ) -> ResourceCheckOutcome:
        snap = self.snapshot()

        required_disk_gb = max(
            self.min_free_disk_gb,
            step.min_disk_gb,
            MIN_DISK_RESERVE_GB if step.lane == "compute_heavy" else 0.0,
        )
        if snap["free_disk_gb"] < required_disk_gb:
            return ResourceCheckOutcome(
                allowed=False,
                reason=(
                    f"Insufficient disk space ({snap['free_disk_gb']} GB free < "
                    f"{required_disk_gb} GB required)"
                ),
                wait_for_resource=True,
                blocked=False,
                snapshot=snap,
            )

        ram_limit_mb = self.resource_manager.max_ram_mb or (RAM_HARD_LIMIT_GB * 1024)
        if snap["ram_mb"] >= min(ram_limit_mb, RAM_HARD_LIMIT_GB * 1024):
            return ResourceCheckOutcome(
                allowed=False,
                reason=(
                    f"Process RAM {snap['ram_mb']} MB exceeds hard limit "
                    f"{min(ram_limit_mb, RAM_HARD_LIMIT_GB * 1024)} MB"
                ),
                wait_for_resource=True,
                blocked=False,
                snapshot=snap,
            )

        requested_paid_gpu = step.requires_paid_gpu or bool(payload.get("use_paid_gpu", False))
        if requested_paid_gpu and not has_paid_gpu_approval:
            return ResourceCheckOutcome(
                allowed=False,
                reason="Paid cloud GPU compute is blocked without an approved Tier-2 budget token.",
                wait_for_resource=False,
                blocked=True,
                snapshot=snap,
            )

        if step.lane == "compute_heavy" and not snap["vram_available"]:
            training_cfg = payload.get("training_config") or payload.get("train_config") or {}
            model_cfg = payload.get("model_config") or {}
            batch = int(training_cfg.get("batch_size", payload.get("batch_size", MAX_CPU_BATCH_SIZE)))
            steps = int(
                training_cfg.get(
                    "max_steps",
                    payload.get("max_steps", payload.get("steps", MAX_CPU_TRAINING_STEPS)),
                )
            )
            seq = int(
                model_cfg.get(
                    "max_seq_len",
                    payload.get("block_size", payload.get("seq_len", payload.get("seq", MAX_CPU_SEQUENCE_LENGTH))),
                )
            )
            params = int(payload.get("estimated_params", payload.get("params", 0)))
            cpu_threads = int(training_cfg.get("cpu_threads", payload.get("cpu_threads", MAX_CPU_THREADS)))
            exp_timeout = float(
                payload.get(
                    "experiment_timeout_sec",
                    payload.get("timeout_seconds", MAX_EXPERIMENT_TIMEOUT_SECONDS),
                )
            )
            loop_timeout = float(payload.get("loop_timeout_sec", MAX_LOOP_TIMEOUT_SECONDS))

            if (
                batch <= 0
                or batch > MAX_CPU_BATCH_SIZE
                or steps <= 0
                or steps > MAX_CPU_TRAINING_STEPS
                or seq <= 0
                or seq > MAX_CPU_SEQUENCE_LENGTH
                or params < 0
                or params > MAX_CPU_MODEL_PARAMETERS
                or cpu_threads <= 0
                or cpu_threads > MAX_CPU_THREADS
                or exp_timeout <= 0
                or exp_timeout > MAX_EXPERIMENT_TIMEOUT_SECONDS
                or loop_timeout <= 0
                or loop_timeout > MAX_LOOP_TIMEOUT_SECONDS
            ):
                return ResourceCheckOutcome(
                    allowed=False,
                    reason=(
                        "Requested workload exceeds CPU compute bounds "
                        f"(params<={MAX_CPU_MODEL_PARAMETERS}, seq<={MAX_CPU_SEQUENCE_LENGTH}, "
                        f"batch<={MAX_CPU_BATCH_SIZE}, steps<={MAX_CPU_TRAINING_STEPS}, "
                        f"cpu_threads<={MAX_CPU_THREADS}, exp_timeout<={MAX_EXPERIMENT_TIMEOUT_SECONDS}s, "
                        f"loop_timeout<={MAX_LOOP_TIMEOUT_SECONDS}s)."
                    ),
                    wait_for_resource=False,
                    blocked=True,
                    snapshot=snap,
                )

        # Validate CostLimits configuration fail-closed
        try:
            cost_controller_from_env()
        except ValueError as exc:
            return ResourceCheckOutcome(
                allowed=False,
                reason=f"Invalid training cost configuration: {exc}",
                wait_for_resource=False,
                blocked=True,
                snapshot=snap,
            )

        return ResourceCheckOutcome(
            allowed=True,
            reason="ok",
            wait_for_resource=False,
            blocked=False,
            snapshot=snap,
        )

