"""Add user-owned native inference usage and quota policies."""

from alembic import op
import sqlalchemy as sa


revision = "20261120_05"
down_revision = "20261120_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_quota_policies",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("max_requests", sa.Integer(), nullable=True),
        sa.Column("max_input_tokens", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("max_total_tokens", sa.Integer(), nullable=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "max_requests IS NOT NULL OR max_input_tokens IS NOT NULL "
            "OR max_output_tokens IS NOT NULL OR max_total_tokens IS NOT NULL",
            name="ck_user_quota_policy_has_limit",
        ),
        sa.CheckConstraint(
            "(max_requests IS NULL OR max_requests >= 0) AND "
            "(max_input_tokens IS NULL OR max_input_tokens >= 0) AND "
            "(max_output_tokens IS NULL OR max_output_tokens >= 0) AND "
            "(max_total_tokens IS NULL OR max_total_tokens >= 0)",
            name="ck_user_quota_policy_nonnegative",
        ),
        sa.CheckConstraint(
            "(window_started_at IS NULL AND window_ends_at IS NULL) OR "
            "(window_started_at IS NOT NULL AND window_ends_at IS NOT NULL "
            "AND window_ends_at > window_started_at)",
            name="ck_user_quota_policy_window",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "inference_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_inference_usage_status",
        ),
        sa.CheckConstraint("input_tokens >= 0", name="ck_inference_usage_input"),
        sa.CheckConstraint("output_tokens >= 0", name="ck_inference_usage_output"),
        sa.CheckConstraint(
            "reserved_tokens >= 0",
            name="ck_inference_usage_reserved",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_inference_usage_request_id"),
    )
    op.create_index("ix_inference_usage_user_id", "inference_usage", ["user_id"])
    op.create_index(
        "ix_inference_usage_conversation_id",
        "inference_usage",
        ["conversation_id"],
    )
    op.create_index(
        "ix_inference_usage_user_created",
        "inference_usage",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_inference_usage_user_created", table_name="inference_usage")
    op.drop_index(
        "ix_inference_usage_conversation_id",
        table_name="inference_usage",
    )
    op.drop_index("ix_inference_usage_user_id", table_name="inference_usage")
    op.drop_table("inference_usage")
    op.drop_table("user_quota_policies")
