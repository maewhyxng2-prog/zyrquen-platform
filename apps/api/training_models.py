import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    JSON,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import mapped_column

from database import Base
from models import User  # noqa: F401 - register the users table before migrations


class TrainingRun(Base):
    __tablename__ = "training_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_training_runs_status",
        ),
    )

    id = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = mapped_column(String(16), nullable=False, default="queued")
    dataset_version = mapped_column(String(64), nullable=False)
    training_config = mapped_column(JSON, nullable=False)
    model_config = mapped_column(JSON, nullable=False)
    result = mapped_column(JSON, nullable=True)
    error_message = mapped_column(Text, nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at = mapped_column(DateTime(timezone=True), nullable=True)
