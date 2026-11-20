from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class ConversationMessageCreate(BaseModel):
    id: UUID
    role: Literal["user"]
    content: str = Field(min_length=1, max_length=65536)


class ConversationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ConversationSummary(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationResponse(ConversationSummary):
    messages: list[ConversationMessageResponse]
