"""ZYRQUEN Central Native Workflow Engine & Tier-2 Approval Gate Registry (pure stdlib)."""

from __future__ import annotations

import os
from pathlib import Path

from apps.core.workflow.dag import resolve_ready_steps, validate_dag
from apps.core.workflow.governance import ApprovalViolationError, WorkflowGovernance
from apps.core.workflow.models import (
    APPROVAL_TIERS,
    ChecksumMismatchError,
    LANES,
    LeakageGateFailedError,
    NaNInfWorkflowError,
    NonRetryableWorkflowError,
    OutOfMemoryWorkflowError,
    RUN_STATUSES,
    STEP_STATUSES,
    StepExecutionResult,
    TRIGGER_TYPES,
    TransientWorkflowError,
    VERDICT_STATUSES,
    WORKFLOW_GROUPS,
    WorkflowDefinition,
    WorkflowError,
    WorkflowStepSpec,
    WorkflowValidationError,
    utc_now_iso,
)
from apps.core.workflow.orchestrator import CentralWorkflowOrchestrator
from apps.core.workflow.registry import WorkflowRegistry
from apps.core.workflow.resource_guard import WorkflowResourceGuard
from apps.core.workflow.store import WorkflowStore


def create_default_orchestrator() -> CentralWorkflowOrchestrator:
    data_dir = os.getenv("ZYRQUEN_DATA_DIR", "").strip()
    env_db = os.getenv("ZYRQUEN_WORKFLOW_DB_PATH", "").strip()
    env_secret = os.getenv("ZYRQUEN_APPROVAL_SECRET", "").strip() or None
    work_dir = Path(data_dir) / "workflow" if data_dir else Path(".")
    db_path: str | Path = (
        Path(env_db)
        if env_db
        else (Path(data_dir) / "workflow" / "workflow.db" if data_dir else "/tmp/zyrquen_workflow.db")
    )
    return CentralWorkflowOrchestrator(
        db_path=db_path,
        work_dir=work_dir,
        approval_secret=env_secret,
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
    "TRIGGER_TYPES",
    "TransientWorkflowError",
    "VERDICT_STATUSES",
    "WORKFLOW_GROUPS",
    "WorkflowDefinition",
    "WorkflowError",
    "WorkflowGovernance",
    "WorkflowRegistry",
    "WorkflowResourceGuard",
    "WorkflowStepSpec",
    "WorkflowStore",
    "WorkflowValidationError",
    "create_default_orchestrator",
    "resolve_ready_steps",
    "utc_now_iso",
    "validate_dag",
]
