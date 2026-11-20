
"""Request and response schemas for ZYRQUEN evaluation API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


EvaluationStatus = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
]


class EvaluationRunCreate(BaseModel):
    """Request to create a native model evaluation run."""

    model_version: str = Field(
        min_length=1,
        max_length=128,
    )

    checkpoint_id: str | None = Field(
        default=None,
        max_length=255,
    )

    dataset_id: str = Field(
        min_length=1,
        max_length=255,
    )

    dataset_checksum: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-fA-F0-9]{64}$",
    )


class EvaluationRunResponse(BaseModel):
    """Public representation of an evaluation run."""

    id: str
    model_version: str
    checkpoint_id: str | None
    dataset_id: str
    dataset_checksum: str
    status: EvaluationStatus
    sample_count: int
    token_count: int
    metrics: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class EvaluationRunListResponse(BaseModel):
    """Paginated evaluation run list."""

    items: list[EvaluationRunResponse]
    total: int
    limit: int
    offset: int
