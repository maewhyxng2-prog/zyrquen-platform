"""ZYRQUEN Central Native Workflow Engine package."""

from __future__ import annotations

import os
from pathlib import Path

from apps.core.workflow.dag import validate_dag
from apps.core.workflow.models import (
    APPROVAL_TIERS,
    LANES,
    RUN_STATUSES,
    STEP_STATUSES,
    VERDICT_STATUSES,
    WORKFLOW_GROUPS,
    ApprovalViolationError,
    ChecksumMismatchError,
    LeakageGateFailedError,
    NaNInfWorkflowError,
    NonRetryableWorkflowError,
    OutOfMemoryWorkflowError,
    StepExecutionResult,
    TransientWorkflowError,
    WorkflowDefinition,
    WorkflowError,
    WorkflowStepSpec,
    WorkflowValidationError,
)
from apps.core.workflow.orchestrator import CentralWorkflowOrchestrator


def create_default_orchestrator() -> CentralWorkflowOrchestrator:
    db_path = Path(os.getenv("ZYRQUEN_WORKFLOW_DB_PATH", "/tmp/zyrquen_workflow.db"))
    scheduler_sec = float(os.getenv("ZYRQUEN_WORKFLOW_SCHEDULER_SEC", "60"))
    return CentralWorkflowOrchestrator(
        db_path=db_path,
        work_dir=Path.cwd(),
        scheduler_interval_sec=scheduler_sec,
    )


__all__ = [
    "APPROVAL_TIERS",
    "ApprovalViolationError",
    "CentralWorkflowOrchestrator",
    "ChecksumMismatchError",
    "LANES",
    "LeakageGateFailedError",
    "NaNInfWorkflowError",
    "NonRetryableWorkflowError",
    "OutOfMemoryWorkflowError",
    "RUN_STATUSES",
    "STEP_STATUSES",
    "StepExecutionResult",
    "TransientWorkflowError",
    "VERDICT_STATUSES",
    "WORKFLOW_GROUPS",
    "WorkflowDefinition",
    "WorkflowError",
    "WorkflowStepSpec",
    "WorkflowValidationError",
    "create_default_orchestrator",
    "validate_dag",
]
