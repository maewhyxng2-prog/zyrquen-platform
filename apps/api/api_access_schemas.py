from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiKeyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    expires_at: datetime

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("ชื่อ API Key ต้องไม่เว้นว่าง")
        return normalized

    @field_validator("expires_at")
    @classmethod
    def require_future_timezone_aware_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("วันหมดอายุ API Key ต้องระบุเขตเวลา")
        if value <= datetime.now(timezone.utc):
            raise ValueError("วันหมดอายุ API Key ต้องอยู่ในอนาคต")
        return value


class ApiKeyMetadata(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    scope: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyMetadata):
    key: str


class ApiKeyRevoked(BaseModel):
    id: UUID
    revoked: bool


class ApiKeyUsageSummary(BaseModel):
    key_id: UUID
    successful_requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    updated_at: datetime | None


class AdminUserSummary(BaseModel):
    id: UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime


class AdminOverview(BaseModel):
    users: int
    successful_inference_requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    active_api_keys: int
    configured_quota_policies: int
    active_quota_policies: int
    native_ai: dict[str, object]


class AdminAuditEntry(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    action: str
    resource_id: str | None
    created_at: datetime
