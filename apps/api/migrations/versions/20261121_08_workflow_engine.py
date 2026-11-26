"""Add Central Native Workflow Engine tables."""

from alembic import op
import sqlalchemy as sa


revision = "20261121_08"
down_revision = "20261120_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_key", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("group_name", sa.String(length=32), nullable=False),
        sa.Column("dag_spec", sa.JSON(), nullable=False),
        sa.Column("default_tier", sa.String(length=24), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_key", "version", name="uq_workflow_definitions_key_version"),
    )
    op.create_index("ix_workflow_definitions_workflow_key", "workflow_definitions", ["workflow_key"])
    op.create_index("ix_workflow_definitions_group_name", "workflow_definitions", ["group_name"])

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_key", sa.String(length=64), nullable=False),
        sa.Column("workflow_version", sa.String(length=32), nullable=False),
        sa.Column("trigger_type", sa.String(length=24), nullable=False),
        sa.Column("trigger_dedup_key", sa.String(length=128), nullable=True),
        sa.Column("trigger_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="50", nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("checkpoint_cursor", sa.JSON(), nullable=True),
        sa.Column("resource_snapshot", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trigger_dedup_key"),
    )
    op.create_index("ix_workflow_runs_workflow_key", "workflow_runs", ["workflow_key"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])

    op.create_table(
        "workflow_step_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("lane", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="2", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "step_key", name="uq_workflow_step_runs_run_step"),
    )
    op.create_index("ix_workflow_step_runs_run_id", "workflow_step_runs", ["run_id"])

    op.create_table(
        "workflow_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=255), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("signature_hmac", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_approvals_run_id", "workflow_approvals", ["run_id"])
    op.create_index("ix_workflow_approvals_status", "workflow_approvals", ["status"])

    op.create_table(
        "workflow_audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("step_key", sa.String(length=64), nullable=True),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("resource", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_audit_logs_run_id", "workflow_audit_logs", ["run_id"])
    op.create_index("ix_workflow_audit_logs_created_at", "workflow_audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_workflow_audit_logs_created_at", table_name="workflow_audit_logs")
    op.drop_index("ix_workflow_audit_logs_run_id", table_name="workflow_audit_logs")
    op.drop_table("workflow_audit_logs")

    op.drop_index("ix_workflow_approvals_status", table_name="workflow_approvals")
    op.drop_index("ix_workflow_approvals_run_id", table_name="workflow_approvals")
    op.drop_table("workflow_approvals")

    op.drop_index("ix_workflow_step_runs_run_id", table_name="workflow_step_runs")
    op.drop_table("workflow_step_runs")

    op.drop_index("ix_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_workflow_key", table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_index("ix_workflow_definitions_group_name", table_name="workflow_definitions")
    op.drop_index("ix_workflow_definitions_workflow_key", table_name="workflow_definitions")
    op.drop_table("workflow_definitions")
