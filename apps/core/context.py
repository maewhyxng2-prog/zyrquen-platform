
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class InferenceContext(BaseModel):
    user_id: UUID
    prompt: str = Field(min_length=1, max_length=4096)

    max_tokens: int = Field(
        default=256,
        ge=1,
        le=1024,
    )

    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
    )

    request_id: UUID = Field(default_factory=uuid4)
