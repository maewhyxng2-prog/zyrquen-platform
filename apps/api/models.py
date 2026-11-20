import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import mapped_column

from apps.api.database import Base


class User(Base):
    __tablename__ = "users"

    id = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4
    )

    email = mapped_column(
        String(320),
        unique=True,
        index=True,
        nullable=False
    )

    password_hash = mapped_column(
        String(255),
        nullable=False
    )

    is_active = mapped_column(
        Boolean,
        default=True,
        nullable=False
    )

    created_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti = mapped_column(
        String(64),
        primary_key=True,
    )

    user_id = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    expires_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    revoked_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
