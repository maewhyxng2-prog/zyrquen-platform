import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    false,
    func,
)
from sqlalchemy.orm import mapped_column

from apps.api.database import Base
from apps.api.models import User  # noqa: F401


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(
            "scope = 'native:inference'",
            name="ck_api_keys_scope",
        ),
        CheckConstraint(
            "auto_rotate_interval_days IS NULL OR (auto_rotate_interval_days >= 1 AND auto_rotate_interval_days <= 365)",
            name="ck_api_keys_auto_rotate_interval",
        ),
        UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        Index("ix_api_keys_user_created", "user_id", "created_at"),
        Index("ix_api_keys_next_rotation_at", "next_rotation_at"),
    )

    id = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = mapped_column(String(80), nullable=False)
    key_prefix = mapped_column(String(16), nullable=False)
    key_hash = mapped_column(String(64), nullable=False)
    scope = mapped_column(String(32), nullable=False)
    created_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at = mapped_column(DateTime(timezone=True), nullable=True)
    auto_rotate_enabled = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    auto_rotate_interval_days = mapped_column(Integer, nullable=True)
    last_rotated_at = mapped_column(DateTime(timezone=True), nullable=True)
    next_rotation_at = mapped_column(DateTime(timezone=True), nullable=True)
    rotation_count = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created", "created_at"),
        Index("ix_audit_logs_actor_created", "actor_user_id", "created_at"),
    )

    id = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_user_id = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action = mapped_column(String(64), nullable=False)
    resource_id = mapped_column(String(64), nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class LoginRateLimit(Base):
    __tablename__ = "login_rate_limits"
    __table_args__ = (
        CheckConstraint(
            "failed_attempts >= 0",
            name="ck_login_rate_limits_failed_attempts",
        ),
    )

    key_hash = mapped_column(String(64), primary_key=True)
    failed_attempts = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    window_started_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    blocked_until = mapped_column(DateTime(timezone=True), nullable=True)
