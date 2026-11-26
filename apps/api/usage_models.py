import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import mapped_column

from apps.api.database import Base
from apps.api.models import User  # noqa: F401


class InferenceUsage(Base):
    __tablename__ = "inference_usage"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_inference_usage_request_id"),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_inference_usage_status",
        ),
        CheckConstraint("input_tokens >= 0", name="ck_inference_usage_input"),
        CheckConstraint("output_tokens >= 0", name="ck_inference_usage_output"),
        CheckConstraint("reserved_tokens >= 0", name="ck_inference_usage_reserved"),
        Index("ix_inference_usage_user_created", "user_id", "created_at"),
    )

    id = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id = mapped_column(
        Uuid,
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    api_key_id = mapped_column(
        Uuid,
        ForeignKey("api_keys.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    request_id = mapped_column(Uuid, nullable=False)
    request_fingerprint = mapped_column(String(64), nullable=False)
    model_version = mapped_column(String(128), nullable=True)
    status = mapped_column(String(16), nullable=False)
    input_tokens = mapped_column(Integer, nullable=False, default=0)
    output_tokens = mapped_column(Integer, nullable=False, default=0)
    reserved_tokens = mapped_column(Integer, nullable=False, default=0)
    lease_expires_at = mapped_column(DateTime(timezone=True), nullable=False)
    created_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)


class UserQuotaPolicy(Base):
    __tablename__ = "user_quota_policies"
    __table_args__ = (
        CheckConstraint(
            "max_requests IS NOT NULL OR max_input_tokens IS NOT NULL "
            "OR max_output_tokens IS NOT NULL OR max_total_tokens IS NOT NULL",
            name="ck_user_quota_policy_has_limit",
        ),
        CheckConstraint(
            "(max_requests IS NULL OR max_requests >= 0) AND "
            "(max_input_tokens IS NULL OR max_input_tokens >= 0) AND "
            "(max_output_tokens IS NULL OR max_output_tokens >= 0) AND "
            "(max_total_tokens IS NULL OR max_total_tokens >= 0)",
            name="ck_user_quota_policy_nonnegative",
        ),
        CheckConstraint(
            "(window_started_at IS NULL AND window_ends_at IS NULL) OR "
            "(window_started_at IS NOT NULL AND window_ends_at IS NOT NULL "
            "AND window_ends_at > window_started_at)",
            name="ck_user_quota_policy_window",
        ),
    )

    user_id = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    max_requests = mapped_column(Integer, nullable=True)
    max_input_tokens = mapped_column(Integer, nullable=True)
    max_output_tokens = mapped_column(Integer, nullable=True)
    max_total_tokens = mapped_column(Integer, nullable=True)
    window_started_at = mapped_column(DateTime(timezone=True), nullable=True)
    window_ends_at = mapped_column(DateTime(timezone=True), nullable=True)
