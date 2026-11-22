"""api_keys auto rotate columns

Revision ID: 20261122_09
Revises: 20261121_08
"""
from alembic import op
import sqlalchemy as sa

revision = "20261122_09"
down_revision = "20261121_08"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("api_keys", sa.Column("auto_rotate_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("api_keys", sa.Column("auto_rotate_interval_days", sa.Integer(), nullable=True))
    op.add_column("api_keys", sa.Column("last_rotated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("api_keys", sa.Column("next_rotation_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("api_keys", sa.Column("rotation_count", sa.Integer(), nullable=False, server_default="0"))

def downgrade():
    op.drop_column("api_keys", "rotation_count")
    op.drop_column("api_keys", "next_rotation_at")
    op.drop_column("api_keys", "last_rotated_at")
    op.drop_column("api_keys", "auto_rotate_interval_days")
    op.drop_column("api_keys", "auto_rotate_enabled")
