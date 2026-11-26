"""Add persistent login brute-force throttling."""

from alembic import op
import sqlalchemy as sa


revision = "20261120_07"
down_revision = "20261120_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_rate_limits",
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "failed_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "failed_attempts >= 0",
            name="ck_login_rate_limits_failed_attempts",
        ),
        sa.PrimaryKeyConstraint("key_hash"),
    )
    op.create_index(
        "ix_login_rate_limits_window_started_at",
        "login_rate_limits",
        ["window_started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_login_rate_limits_window_started_at",
        table_name="login_rate_limits",
    )
    op.drop_table("login_rate_limits")
