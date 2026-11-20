
"""ZYRQUEN Ω∞ evaluation database models."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvaluationRun(Base):
    """Stores the lifecycle and results of a native evaluation run."""

    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    user_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    model_version: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    checkpoint_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    dataset_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    dataset_checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="queued",
        index=True,
    )

    sample_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    token_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    metrics: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    metadata_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_evaluation_runs_user_created",
            "user_id",
            "created_at",
        ),
    )
