
"""Add persistent native evaluation run records."""

from alembic import op
import sqlalchemy as sa


revision = "20261120_02"
down_revision = "20261120_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=255), nullable=True),
        sa.Column("dataset_id", sa.String(length=255), nullable=False),
        sa.Column("dataset_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "sample_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "token_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "metrics",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "metadata_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_evaluation_runs_status",
        ),
        sa.CheckConstraint(
            "sample_count >= 0 AND token_count >= 0",
            name="ck_evaluation_runs_counts_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_evaluation_runs_user_id",
        "evaluation_runs",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_evaluation_runs_model_version",
        "evaluation_runs",
        ["model_version"],
        unique=False,
    )

    op.create_index(
        "ix_evaluation_runs_status",
        "evaluation_runs",
        ["status"],
        unique=False,
    )

    op.create_index(
        "ix_evaluation_runs_user_created",
        "evaluation_runs",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evaluation_runs_user_created",
        table_name="evaluation_runs",
    )
    op.drop_index(
        "ix_evaluation_runs_status",
        table_name="evaluation_runs",
    )
    op.drop_index(
        "ix_evaluation_runs_model_version",
        table_name="evaluation_runs",
    )
    op.drop_index(
        "ix_evaluation_runs_user_id",
        table_name="evaluation_runs",
    )
    op.drop_table("evaluation_runs")
