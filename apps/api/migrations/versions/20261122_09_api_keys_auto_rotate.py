"""Add API key auto-rotation columns and constraint."""

from alembic import op
import sqlalchemy as sa


revision = "20261122_09"
down_revision = "20261121_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column(
            "auto_rotate_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "api_keys",
        sa.Column("auto_rotate_interval_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "api_keys",
        sa.Column("last_rotated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "api_keys",
        sa.Column("next_rotation_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "api_keys",
        sa.Column(
            "rotation_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_api_keys_auto_rotate_interval",
        "api_keys",
        "auto_rotate_interval_days IS NULL OR (auto_rotate_interval_days >= 1 AND auto_rotate_interval_days <= 365)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_api_keys_auto_rotate_interval",
        "api_keys",
        type_="check",
    )
    op.drop_column("api_keys", "rotation_count")
    op.drop_column("api_keys", "next_rotation_at")
    op.drop_column("api_keys", "last_rotated_at")
    op.drop_column("api_keys", "auto_rotate_interval_days")
    op.drop_column("api_keys", "auto_rotate_enabled")
