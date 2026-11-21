"""Pydantic request & response schemas for Workflow Engine & Model Registry API."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class TriggerWorkflowRequest(BaseModel):
    workflow_key: str = Field(..., min_length=2, max_length=64)
    version: str | None = Field(default=None, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)
    dedup_key: str | None = Field(default=None, max_length=128)
    execute_async: bool = False


class ApprovalDecisionRequest(BaseModel):
    approve: bool
    reason: str = Field(default="", max_length=500)


class ModelPromoteRequest(BaseModel):
    approval_id: str | None = Field(default=None, max_length=64)


class ModelRollbackRequest(BaseModel):
    to_version: str | None = Field(default=None, max_length=64)
    approval_id: str | None = Field(default=None, max_length=64)
