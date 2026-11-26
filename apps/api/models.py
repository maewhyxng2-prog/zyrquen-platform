import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import mapped_column

from apps.api.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'admin')",
            name="ck_users_role",
        ),
    )

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

    role = mapped_column(
        String(32),
        default="user",
        index=True,
        nullable=False,
        server_default="user",
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


class Conversation(Base):
    __tablename__ = "conversations"

    id = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = mapped_column(String(80), nullable=False)
    created_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_conversation_messages_sequence",
        ),
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_conversation_messages_role",
        ),
        CheckConstraint("sequence > 0", name="ck_conversation_messages_sequence"),
    )

    id = mapped_column(Uuid, primary_key=True)
    conversation_id = mapped_column(
        Uuid,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence = mapped_column(Integer, nullable=False)
    role = mapped_column(String(16), nullable=False)
    content = mapped_column(Text, nullable=False)
    created_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
