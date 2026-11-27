from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserRegister(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=12, max_length=128)


class UserLogin(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: str = "user"
    is_active: bool


class EmailVerifyRequest(BaseModel):
    token: str = Field(min_length=16, max_length=1024)

