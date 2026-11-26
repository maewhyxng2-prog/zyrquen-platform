from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class InferenceUsageResponse(BaseModel):
    request_id: UUID
    status: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    model_version: str | None
    created_at: datetime
    completed_at: datetime | None


class UsageSummaryResponse(BaseModel):
    successful_requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    updated_at: datetime | None
    records: list[InferenceUsageResponse]


class QuotaResponse(BaseModel):
    configured: bool
    active: bool
    max_requests: int | None
    max_input_tokens: int | None
    max_output_tokens: int | None
    max_total_tokens: int | None
    window_started_at: datetime | None
    window_ends_at: datetime | None
    successful_requests: int
    running_requests: int
    requests_in_use: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
