"""
Resource & Workload Manager for ZYRQUEN Tool Center.
----------------------------------------------------
Reuses `zyrquen_core.get_system_metrics()` (real /proc/meminfo, /proc/loadavg,
CPU core count, disk usage) to enforce concurrency limits, RAM/Disk safety
thresholds, and per-task execution budgets without fabricating resource metrics.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

import zyrquen_core as zc


@dataclass(frozen=True)
class ResourceBudget:
    max_concurrent_jobs: int = 4
    default_timeout_s: float = 8.0
    max_output_bytes: int = 131_072
    min_free_ram_mb: float = 96.0
    min_free_disk_mb: float = 48.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "default_timeout_s": self.default_timeout_s,
            "max_output_bytes": self.max_output_bytes,
            "min_free_ram_mb": self.min_free_ram_mb,
            "min_free_disk_mb": self.min_free_disk_mb,
        }


class ResourceManager:
    """Thread-safe workload admission controller and hardware budget monitor."""

    def __init__(self, budget: ResourceBudget | None = None) -> None:
        self._lock = threading.Lock()
        self._active_jobs = 0
        self._total_admitted = 0
        self._total_rejected = 0
        self._budget = budget or ResourceBudget()

    def snapshot(self) -> dict[str, Any]:
        sys_metrics = zc.get_system_metrics()
        cpu_cores = max(1, int(sys_metrics.get("cpu_count") or sys_metrics.get("cpu_cores") or 1))
        hw_cap = min(self._budget.max_concurrent_jobs, max(1, cpu_cores))
        with self._lock:
            active = self._active_jobs
            admitted = self._total_admitted
            rejected = self._total_rejected
        return {
            "system": sys_metrics,
            "budget": self._budget.to_dict(),
            "effective_max_workers": hw_cap,
            "active_jobs": active,
            "available_slots": max(0, hw_cap - active),
            "total_admitted": admitted,
            "total_rejected": rejected,
        }

    def evaluate_admission(
        self,
        *,
        requested_workers: int = 1,
        estimated_timeout_s: float | None = None,
        min_free_ram_mb: float | None = None,
        min_free_disk_mb: float | None = None,
    ) -> dict[str, Any]:
        sys_metrics = zc.get_system_metrics()
        cpu_cores = max(1, int(sys_metrics.get("cpu_count") or sys_metrics.get("cpu_cores") or 1))
        hw_cap = min(self._budget.max_concurrent_jobs, max(1, cpu_cores))

        ram_avail_mb = (
            sys_metrics.get("mem_available_mb")
            if sys_metrics.get("mem_available_mb") is not None
            else sys_metrics.get("ram_available_mb")
        )
        disk_free_gb = sys_metrics.get("disk_free_gb")
        disk_free_mb = float(disk_free_gb) * 1024.0 if disk_free_gb is not None else None

        ram_floor = self._budget.min_free_ram_mb if min_free_ram_mb is None else float(min_free_ram_mb)
        disk_floor = self._budget.min_free_disk_mb if min_free_disk_mb is None else float(min_free_disk_mb)

        if ram_avail_mb is not None and float(ram_avail_mb) < ram_floor:
            with self._lock:
                self._total_rejected += 1
            return {
                "allowed": False,
                "error_code": "RESOURCE_LIMIT",
                "reason": f"Available RAM ({ram_avail_mb} MB) below safety threshold ({ram_floor} MB).",
                "effective_workers": 0,
                "system": sys_metrics,
            }

        if disk_free_mb is not None and disk_free_mb < disk_floor:
            with self._lock:
                self._total_rejected += 1
            return {
                "allowed": False,
                "error_code": "RESOURCE_LIMIT",
                "reason": f"Free disk ({disk_free_mb:.1f} MB) below safety threshold ({disk_floor} MB).",
                "effective_workers": 0,
                "system": sys_metrics,
            }

        with self._lock:
            slots = max(0, hw_cap - self._active_jobs)
            if slots <= 0:
                self._total_rejected += 1
                return {
                    "allowed": False,
                    "error_code": "RESOURCE_LIMIT",
                    "reason": f"Concurrent workload limit reached ({self._active_jobs}/{hw_cap} active).",
                    "effective_workers": 0,
                    "system": sys_metrics,
                }
            granted_workers = max(1, min(int(requested_workers), slots))
            self._total_admitted += 1

        timeout_s = min(
            30.0,
            max(0.2, float(estimated_timeout_s or self._budget.default_timeout_s)),
        )
        return {
            "allowed": True,
            "error_code": None,
            "effective_workers": granted_workers,
            "timeout_s": timeout_s,
            "max_output_bytes": self._budget.max_output_bytes,
            "system": sys_metrics,
        }

    def acquire_slot(self, count: int = 1) -> bool:
        with self._lock:
            if self._active_jobs + count > self._budget.max_concurrent_jobs:
                return False
            self._active_jobs += count
            return True

    def release_slot(self, count: int = 1) -> None:
        with self._lock:
            self._active_jobs = max(0, self._active_jobs - count)


_RESOURCE_MANAGER: ResourceManager | None = None


def get_resource_manager() -> ResourceManager:
    global _RESOURCE_MANAGER
    if _RESOURCE_MANAGER is None:
        _RESOURCE_MANAGER = ResourceManager()
    return _RESOURCE_MANAGER
