"""Add persistent revoked_tokens table for server-side session invalidation."""

from alembic import op
import sqlalchemy as sa


revision = "20261120_03"
down_revision = "20261120_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index(
        "ix_revoked_tokens_user_id",
        "revoked_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_revoked_tokens_expires_at",
        "revoked_tokens",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_user_id", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
