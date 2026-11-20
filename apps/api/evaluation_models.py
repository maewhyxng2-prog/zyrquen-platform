import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import mapped_column

from apps.api.database import Base
from apps.api.models import User  # noqa: F401 - register the users table


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_evaluation_runs_status",
        ),
        CheckConstraint(
            "sample_count >= 0 AND token_count >= 0",
            name="ck_evaluation_runs_counts_nonnegative",
        ),
        Index(
            "ix_evaluation_runs_user_created",
            "user_id",
            "created_at",
        ),
    )

    id = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_version = mapped_column(String(128), nullable=False, index=True)
    checkpoint_id = mapped_column(String(255), nullable=True)
    dataset_id = mapped_column(String(255), nullable=False)
    dataset_checksum = mapped_column(String(64), nullable=False)
    status = mapped_column(
        String(32),
        nullable=False,
        default="queued",
        server_default="queued",
        index=True,
    )
    sample_count = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    token_count = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    metrics = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    metadata_json = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    error_message = mapped_column(Text, nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)
