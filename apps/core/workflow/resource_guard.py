"""Unified CPU / RAM / GPU / Disk and CostLimits Resource Guard for Workflow Engine."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.core.resource import ResourceManager
from apps.core.training.cost_limits import cost_controller_from_env
from apps.core.workflow.models import WorkflowStepSpec


MAX_CPU_MODEL_PARAMETERS = 5_000_000
MAX_CPU_SEQUENCE_LENGTH = 256
MAX_CPU_BATCH_SIZE = 4
MAX_CPU_TRAINING_STEPS = 1_000


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
        min_free_disk_gb: float = 0.25,
    ) -> None:
        self.resource_manager = resource_manager or ResourceManager()
        self.work_dir = Path(work_dir)
        self.min_free_disk_gb = min_free_disk_gb

    def snapshot(self) -> dict[str, Any]:
        snap = self.resource_manager.snapshot()
        target = self.work_dir if self.work_dir.exists() else Path(".")
        disk = shutil.disk_usage(target)
        load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
        return {
            **snap,
            "cpu_count": os.cpu_count() or 1,
            "load_1m": round(load_avg[0], 3),
            "free_disk_gb": round(disk.free / (1024 ** 3), 3),
            "total_disk_gb": round(disk.total / (1024 ** 3), 3),
        }

    def check_step(
        self,
        step: WorkflowStepSpec,
        payload: dict[str, Any],
        *,
        has_paid_gpu_approval: bool = False,
    ) -> ResourceCheckOutcome:
        snap = self.snapshot()

        if snap["free_disk_gb"] < max(self.min_free_disk_gb, step.min_disk_gb):
            return ResourceCheckOutcome(
                allowed=False,
                reason=(
                    f"Insufficient disk space ({snap['free_disk_gb']} GB free < "
                    f"{max(self.min_free_disk_gb, step.min_disk_gb)} GB required)"
                ),
                wait_for_resource=True,
                blocked=False,
                snapshot=snap,
            )

        if self.resource_manager.max_ram_mb and snap["ram_mb"] > self.resource_manager.max_ram_mb:
            return ResourceCheckOutcome(
                allowed=False,
                reason=(
                    f"Process RAM {snap['ram_mb']} MB exceeds configured limit "
                    f"{self.resource_manager.max_ram_mb} MB"
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
            training_cfg = payload.get("training_config") or {}
            model_cfg = payload.get("model_config") or {}
            batch = int(training_cfg.get("batch_size", payload.get("batch_size", 4)))
            steps = int(training_cfg.get("max_steps", payload.get("steps", 960)))
            seq = int(model_cfg.get("max_seq_len", payload.get("seq", 256)))
            params = int(payload.get("estimated_params", 0))
            if (
                batch > MAX_CPU_BATCH_SIZE
                or steps > MAX_CPU_TRAINING_STEPS
                or seq > MAX_CPU_SEQUENCE_LENGTH
                or params > MAX_CPU_MODEL_PARAMETERS
            ):
                return ResourceCheckOutcome(
                    allowed=False,
                    reason=(
                        "Requested workload exceeds CPU compute bounds "
                        f"(params<={MAX_CPU_MODEL_PARAMETERS}, seq<={MAX_CPU_SEQUENCE_LENGTH}, "
                        f"batch<={MAX_CPU_BATCH_SIZE}, steps<={MAX_CPU_TRAINING_STEPS})."
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
