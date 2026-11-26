"""Add persistent training job records without changing users."""

from alembic import op
import sqlalchemy as sa

revision = "20261120_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    baseline_marker_created = False
    if not inspector.has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email", name="uq_users_email"),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)
        op.create_table(
            "zyrquen_migration_baseline",
            sa.Column("created_by_revision", sa.String(length=32), nullable=False),
        )
        op.execute(
            sa.text(
                "INSERT INTO zyrquen_migration_baseline "
                "(created_by_revision) VALUES ('20261120_01')"
            )
        )
        baseline_marker_created = True

    if baseline_marker_created:
        inspector = sa.inspect(bind)

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

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("zyrquen_migration_baseline"):
        op.drop_table("zyrquen_migration_baseline")
        if inspector.has_table("users"):
            op.drop_index("ix_users_email", table_name="users")
            op.drop_table("users")
