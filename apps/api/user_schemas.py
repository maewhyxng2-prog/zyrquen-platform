from uuid import UUID

import re
from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str


class UserProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=5, max_length=320)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(
            r"[^@\s]{1,64}@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}",
            normalized,
        ):
            raise ValueError("A valid email address is required")
        return normalized
