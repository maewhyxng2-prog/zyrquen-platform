"""Core data contracts and canonical status definitions for ZYRQUEN Central Workflow Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


WORKFLOW_GROUPS = (
    "system_ops",
    "data",
    "training",
    "evaluation",
    "knowledge_memory",
    "improvement_proposal",
    "security_governance",
    "project_dev",
)

RUN_STATUSES = (
    "PENDING",
    "WAITING_RESOURCE",
    "WAITING_APPROVAL",
    "RUNNING",
    "VERIFYING",
    "COMPLETED",
    "FAILED",
    "BLOCKED",
    "CANCELLED",
)

STEP_STATUSES = (
    "PENDING",
    "WAITING_RESOURCE",
    "WAITING_APPROVAL",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "BLOCKED",
    "SKIPPED",
)

VERDICT_STATUSES = ("PASS", "FAIL", "BLOCKED", "NOT RUN")
APPROVAL_TIERS = ("tier1_auto", "tier2_approval")
LANES = ("control_ops", "compute_heavy")
TRIGGER_TYPES = ("event", "schedule", "condition", "manual")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowError(RuntimeError):
    """Base workflow engine error."""


class WorkflowValidationError(WorkflowError):
    """Raised when a workflow DAG or schema definition is invalid."""


class NonRetryableWorkflowError(WorkflowError):
    """Base error for fail-closed conditions that must never be retried."""

    error_code = "non_retryable"
    target_run_status = "FAILED"


class OutOfMemoryWorkflowError(NonRetryableWorkflowError):
    error_code = "out_of_memory"
    target_run_status = "FAILED"


class NaNInfWorkflowError(NonRetryableWorkflowError):
    error_code = "nan_inf_loss"
    target_run_status = "FAILED"


class LeakageGateFailedError(NonRetryableWorkflowError):
    error_code = "leakage_gate_failed"
    target_run_status = "BLOCKED"


class ChecksumMismatchError(NonRetryableWorkflowError):
    error_code = "checksum_mismatch"
    target_run_status = "BLOCKED"


class ApprovalViolationError(NonRetryableWorkflowError):
    error_code = "approval_violation"
    target_run_status = "BLOCKED"


class TransientWorkflowError(WorkflowError):
    """Raised when a step hits a transient I/O or lock error eligible for bounded retry."""


@dataclass(frozen=True)
class WorkflowStepSpec:
    step_key: str
    handler_key: str
    description: str = ""
    depends_on: tuple[str, ...] = ()
    lane: str = "control_ops"
    tier: str = "tier1_auto"
    action_type: str = "read_only"
    max_attempts: int = 2
    retry_backoff_sec: float = 0.25
    requires_paid_gpu: bool = False
    estimated_ram_mb: float = 64.0
    min_disk_gb: float = 0.2
    condition_step: str | None = None
    condition_verdict: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_key": self.step_key,
            "handler_key": self.handler_key,
            "description": self.description,
            "depends_on": list(self.depends_on),
            "lane": self.lane,
            "tier": self.tier,
            "action_type": self.action_type,
            "max_attempts": self.max_attempts,
            "retry_backoff_sec": self.retry_backoff_sec,
            "requires_paid_gpu": self.requires_paid_gpu,
            "estimated_ram_mb": self.estimated_ram_mb,
            "min_disk_gb": self.min_disk_gb,
            "condition_step": self.condition_step,
            "condition_verdict": self.condition_verdict,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WorkflowStepSpec:
        return cls(
            step_key=str(raw["step_key"]),
            handler_key=str(raw["handler_key"]),
            description=str(raw.get("description", "")),
            depends_on=tuple(str(d) for d in raw.get("depends_on", ())),
            lane=str(raw.get("lane", "control_ops")),
            tier=str(raw.get("tier", "tier1_auto")),
            action_type=str(raw.get("action_type", "read_only")),
            max_attempts=int(raw.get("max_attempts", 2)),
            retry_backoff_sec=float(raw.get("retry_backoff_sec", 0.25)),
            requires_paid_gpu=bool(raw.get("requires_paid_gpu", False)),
            estimated_ram_mb=float(raw.get("estimated_ram_mb", 64.0)),
            min_disk_gb=float(raw.get("min_disk_gb", 0.2)),
            condition_step=raw.get("condition_step"),
            condition_verdict=raw.get("condition_verdict"),
        )


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_key: str
    version: str
    group_name: str
    title: str
    description: str
    steps: tuple[WorkflowStepSpec, ...]
    default_tier: str = "tier1_auto"
    schedule_interval_sec: int | None = None
    event_triggers: tuple[str, ...] = ()
    is_active: bool = True

    def to_dag_spec(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "schedule_interval_sec": self.schedule_interval_sec,
            "event_triggers": list(self.event_triggers),
            "steps": [step.to_dict() for step in self.steps],
        }

    def step_map(self) -> dict[str, WorkflowStepSpec]:
        return {s.step_key: s for s in self.steps}


@dataclass
class StepExecutionResult:
    verdict: str  # PASS | FAIL | BLOCKED | NOT RUN
    summary: str
    output: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    emitted_events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.verdict not in VERDICT_STATUSES:
            raise WorkflowValidationError(f"Unsupported verdict status: {self.verdict}")
