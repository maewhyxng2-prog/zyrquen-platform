import uuid

from sqlalchemy import Boolean, DateTime, String, Uuid, func
from sqlalchemy.orm import mapped_column

from database import Base


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
