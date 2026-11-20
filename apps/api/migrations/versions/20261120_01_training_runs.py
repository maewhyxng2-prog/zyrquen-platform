"""Add persistent training job records without changing users."""

from alembic import op
import sqlalchemy as sa

revision = "20261120_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("training_config", sa.JSON(), nullable=False),
        sa.Column("model_config", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_training_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_training_runs_owner_id",
        "training_runs",
        ["owner_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_training_runs_owner_id", table_name="training_runs")
    op.drop_table("training_runs")
