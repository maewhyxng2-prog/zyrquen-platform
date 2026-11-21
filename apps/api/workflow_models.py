"""SQLAlchemy models for the ZYRQUEN Central Native Workflow Engine."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import mapped_column

from apps.api.database import Base


class WorkflowDefinitionModel(Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint("workflow_key", "version", name="uq_workflow_definitions_key_version"),
    )

    id = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_key = mapped_column(String(64), nullable=False, index=True)
    version = mapped_column(String(32), nullable=False)
    group_name = mapped_column(String(32), nullable=False, index=True)
    dag_spec = mapped_column(JSON, nullable=False)
    default_tier = mapped_column(String(24), nullable=False, default="tier1_auto")
    is_active = mapped_column(Boolean, nullable=False, default=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WorkflowRunModel(Base):
    __tablename__ = "workflow_runs"

    id = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_key = mapped_column(String(64), nullable=False, index=True)
    workflow_version = mapped_column(String(32), nullable=False)
    trigger_type = mapped_column(String(24), nullable=False)
    trigger_dedup_key = mapped_column(String(128), unique=True, nullable=True)
    trigger_payload = mapped_column(JSON, nullable=False, default=dict)
    status = mapped_column(String(24), nullable=False, index=True)
    priority = mapped_column(Integer, nullable=False, default=50)
    requested_by_user_id = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    checkpoint_cursor = mapped_column(JSON, nullable=True)
    resource_snapshot = mapped_column(JSON, nullable=True)
    error_message = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowStepRunModel(Base):
    __tablename__ = "workflow_step_runs"
    __table_args__ = (
        UniqueConstraint("run_id", "step_key", name="uq_workflow_step_runs_run_step"),
    )

    id = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id = mapped_column(
        Uuid, ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_key = mapped_column(String(64), nullable=False)
    depends_on = mapped_column(JSON, nullable=False, default=list)
    lane = mapped_column(String(24), nullable=False, default="control_ops")
    status = mapped_column(String(24), nullable=False)
    attempt = mapped_column(Integer, nullable=False, default=0)
    max_attempts = mapped_column(Integer, nullable=False, default=2)
    next_retry_at = mapped_column(DateTime(timezone=True), nullable=True)
    evidence = mapped_column(JSON, nullable=True)
    output = mapped_column(JSON, nullable=True)
    error_code = mapped_column(String(64), nullable=True)
    started_at = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowApprovalModel(Base):
    __tablename__ = "workflow_approvals"

    id = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id = mapped_column(
        Uuid, ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_key = mapped_column(String(64), nullable=False)
    action_type = mapped_column(String(64), nullable=False)
    scope = mapped_column(String(255), nullable=False)
    requested_by_user_id = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_user_id = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status = mapped_column(String(24), nullable=False, index=True, default="pending")
    signature_hmac = mapped_column(String(128), nullable=True)
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at = mapped_column(DateTime(timezone=True), nullable=True)
    reason = mapped_column(Text, nullable=False, default="")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WorkflowAuditLogModel(Base):
    __tablename__ = "workflow_audit_logs"

    id = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id = mapped_column(Uuid, nullable=True, index=True)
    step_key = mapped_column(String(64), nullable=True)
    actor_id = mapped_column(String(64), nullable=False)
    event_type = mapped_column(String(64), nullable=False)
    resource = mapped_column(String(255), nullable=False)
    decision = mapped_column(String(32), nullable=False)
    details = mapped_column(JSON, nullable=False, default=dict)
    created_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
