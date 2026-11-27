"""Resource guard for ZYRQUEN Workflow Engine (RAM, Disk, CPU, and paid-GPU checks)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
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


def enforce_cpu_thread_cap(max_threads: int = MAX_CPU_THREADS, torch_mod: Any | None = None) -> int:
    """Cap BLAS/OpenMP and PyTorch thread counts to prevent CPU oversubscription."""
    cap = max(1, int(max_threads))
    cap_str = str(cap)
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "TORCH_NUM_THREADS",
    ):
        os.environ.setdefault(var, cap_str)
    try:
        mod = torch_mod
        if mod is None:
            import torch as mod  # type: ignore

        mod.set_num_threads(cap)
        try:
            mod.set_num_interop_threads(min(cap, max(1, mod.get_num_interop_threads())))
        except Exception:
            pass
    except Exception:
        pass
    return cap


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


def check_disk_reserve(path: str | Path = ".", reserve_gb: float = MIN_DISK_RESERVE_GB) -> tuple[bool, dict[str, Any]]:
    """Check free disk space against required reserve_gb and return (ok, info)."""
    target = Path(path)
    probe_path = target if target.exists() else target.parent
    if not probe_path.exists():
        probe_path = Path(".")
    usage = shutil.disk_usage(probe_path)
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
    """Verify PyTorch runtime availability and CPU thread settings."""
    enforce_cpu_thread_cap(max_threads)
    info: dict[str, Any] = {
        "ok": True,
        "max_threads": int(max_threads),
        "torch_available": False,
        "cuda_available": False,
        "num_threads": None,
    }
    try:
        import torch  # type: ignore

        info["torch_available"] = True
        info["available"] = True
        info["cuda_available"] = bool(torch.cuda.is_available())
        info["num_threads"] = int(torch.get_num_threads())
        if info["num_threads"] > int(max_threads):
            info["ok"] = False
    except Exception as exc:
        info["ok"] = False
        info["error"] = str(exc)
    return info


@dataclass
class TrainingRuntimeGuard:
    """Runtime guard for training loops checking RSS RAM and disk reserve."""

    work_dir: str | Path = "."
    min_free_disk_gb: float = MIN_DISK_RESERVE_GB
    ram_hard_limit_gb: float = RAM_HARD_LIMIT_GB
    max_new_disk_gb: float = MAX_NEW_DISK_GB

    def check_runtime(self, step: int | None = None, loss: float | None = None) -> dict[str, Any]:
        rss_gb = read_process_rss_bytes() / GB
        if rss_gb > self.ram_hard_limit_gb:
            return {
                "ok": False,
                "reason": "ram_hard_limit",
                "step": step,
                "rss_gb": round(rss_gb, 4),
                "hard_limit_gb": self.ram_hard_limit_gb,
            }
        disk_ok, disk = check_disk_reserve(self.work_dir, reserve_gb=self.min_free_disk_gb)
        if not disk_ok:
            return {
                "ok": False,
                "reason": "disk_reserve_violated",
                "step": step,
                "disk": disk,
            }
        return {
            "ok": True,
            "reason": "ok",
            "step": step,
            "rss_gb": round(rss_gb, 4),
            "disk": disk,
        }


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

    def __post_init__(self) -> None:
        if self.resource_manager is not None:
            max_ram_mb = getattr(self.resource_manager, "max_ram_mb", None)
            if isinstance(max_ram_mb, (int, float)) and max_ram_mb > 0:
                self.ram_hard_limit_gb = float(max_ram_mb) / 1024.0

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
    ) -> dict[str, Any]:
        payload = payload or {}
        paid_gpu = bool(use_paid_gpu or payload.get("use_paid_gpu", False))
        approved_gpu = bool(has_paid_gpu_approval or payload.get("approved_paid_gpu", False))
        if paid_gpu and not approved_gpu:
            return GuardOutcome(
                allowed=False,
                blocked=True,
                reason="unapproved_paid_gpu",
                detail="Paid GPU requested without approval.",
            )

        disk_ok, disk = check_disk_reserve(self.work_dir, reserve_gb=self.min_free_disk_gb)
        if not disk_ok:
            return GuardOutcome(
                allowed=False,
                blocked=True,
                reason="disk_reserve_violated",
                detail=disk,
            )

        rss_gb = read_process_rss_bytes() / GB
        if rss_gb > self.ram_hard_limit_gb:
            return GuardOutcome(
                allowed=False,
                blocked=True,
                reason="ram_hard_limit",
                detail={"rss_gb": round(rss_gb, 4), "hard_limit_gb": self.ram_hard_limit_gb},
            )

        step_count = steps if steps is not None else payload.get("steps", payload.get("max_steps"))
        if step_count is not None and int(step_count) > MAX_CPU_TRAINING_STEPS:
            return GuardOutcome(
                allowed=False,
                blocked=True,
                reason="step_limit_exceeded",
                detail={"steps": int(step_count), "max_steps": MAX_CPU_TRAINING_STEPS},
            )

        params_count = (
            estimated_params
            if estimated_params is not None
            else payload.get("estimated_params")
        )
        if params_count is not None:
            params_count = _coerce_params_count(params_count)
            if params_count is None:
                return GuardOutcome(
                    allowed=False,
                    blocked=True,
                    reason="invalid_estimated_params",
                    detail={"max_params": MAX_CPU_MODEL_PARAMETERS},
                )
            if params_count > MAX_CPU_MODEL_PARAMETERS:
                return GuardOutcome(
                    allowed=False,
                    blocked=True,
                    reason="parameter_budget_exceeded",
                    detail={"estimated_params": params_count, "max_params": MAX_CPU_MODEL_PARAMETERS},
                )

        return GuardOutcome(
            allowed=True,
            blocked=False,
            reason="ok",
            detail={"disk": disk, "rss_gb": round(rss_gb, 4)},
        )
