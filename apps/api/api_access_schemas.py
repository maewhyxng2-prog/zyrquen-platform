from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ApiKeyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    expires_at: datetime
    auto_rotate_enabled: bool = False
    auto_rotate_interval_days: int | None = Field(default=None, ge=1, le=365)

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

    @model_validator(mode="after")
    def validate_auto_rotate(self):
        if self.auto_rotate_enabled and self.auto_rotate_interval_days is None:
            raise ValueError("กรุณาระบุจำนวนวันสำหรับ Auto-rotate")
        if not self.auto_rotate_enabled:
            self.auto_rotate_interval_days = None
        return self


class ApiKeyAutoRotateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_rotate_enabled: bool
    auto_rotate_interval_days: int | None = Field(default=None, ge=1, le=365)

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.auto_rotate_enabled and self.auto_rotate_interval_days is None:
            raise ValueError("กรุณาระบุจำนวนวันสำหรับ Auto-rotate")
        if not self.auto_rotate_enabled:
            self.auto_rotate_interval_days = None
        return self


class ApiKeyMetadata(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    scope: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    auto_rotate_enabled: bool = False
    auto_rotate_interval_days: int | None = None
    last_rotated_at: datetime | None = None
    next_rotation_at: datetime | None = None
    rotation_count: int = 0


class ApiKeyCreated(ApiKeyMetadata):
    key: str


class ApiKeyRevoked(BaseModel):
    id: UUID
    revoked: bool


class ApiKeyBulkRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] = Field(min_length=1, max_length=100)


class ApiKeyBulkRevokeResponse(BaseModel):
    revoked_ids: list[UUID]
    revoked_count: int


class ApiKeyDailyUsagePoint(BaseModel):
    date: str
    successful_requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int


class ApiKeyUsageSummary(BaseModel):
    key_id: UUID
    successful_requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    updated_at: datetime | None
    daily_usage: list[ApiKeyDailyUsagePoint] = Field(default_factory=list)


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
