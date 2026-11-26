from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrainingConfigRequest(BaseModel):
    block_size: int = Field(default=128, ge=2, le=256)
    batch_size: int = Field(default=1, ge=1, le=4)
    grad_accum_steps: int = Field(default=1, ge=1, le=8)
    max_steps: int = Field(default=100, ge=1, le=1_000)
    lr: float = Field(default=3e-4, gt=0, le=1)
    min_lr: float = Field(default=3e-5, gt=0, le=1)
    warmup_steps: int = Field(default=10, ge=0, le=1_000)
    weight_decay: float = Field(default=0.1, ge=0, le=10)
    grad_clip: float = Field(default=1.0, gt=0, le=100)
    eval_interval: int = Field(default=200, ge=1, le=10_000_000)
    eval_batches: int = Field(default=4, ge=1, le=20)
    checkpoint_interval: int = Field(default=200, ge=1, le=10_000_000)
    log_interval: int = Field(default=10, ge=1, le=10_000_000)
    seed: int = Field(default=1337, ge=0)

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.min_lr > self.lr:
            raise ValueError("min_lr must not exceed lr.")
        if self.warmup_steps >= self.max_steps:
            raise ValueError("warmup_steps must be less than max_steps.")
        return self


class NativeModelConfigRequest(BaseModel):
    max_seq_len: int = Field(default=256, ge=2, le=256)
    n_layers: int = Field(default=4, ge=1, le=128)
    n_heads: int = Field(default=4, ge=1, le=128)
    d_model: int = Field(default=256, ge=2, le=16384)
    d_ff: int = Field(default=704, ge=1, le=65536)
    dropout: float = Field(default=0.0, ge=0, lt=1)
    rope_theta: float = Field(default=10000.0, gt=0)
    norm_eps: float = Field(default=1e-5, gt=0)
    tie_embeddings: bool = True

    @model_validator(mode="after")
    def validate_head_dimensions(self):
        if self.d_model % self.n_heads:
            raise ValueError("d_model must be divisible by n_heads.")
        if (self.d_model // self.n_heads) % 2:
            raise ValueError("head dimension must be even for RoPE.")
        return self


class TrainingRunRequest(BaseModel):
    dataset_version: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    approval_id: str | None = Field(default=None, max_length=128)
    training: TrainingConfigRequest = Field(
        default_factory=TrainingConfigRequest
    )
    model: NativeModelConfigRequest = Field(
        default_factory=NativeModelConfigRequest
    )


class TrainingRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: Literal["queued", "running", "completed", "failed"]
    dataset_version: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: dict | None
    error_message: str | None


class CheckpointTelemetry(BaseModel):
    step: int
    file: str
    size_bytes: int
    sha256: str


class TrainingTelemetryResponse(BaseModel):
    run_id: UUID
    status: Literal["queued", "running", "completed", "failed"]
    metrics: list[dict]
    checkpoints: list[CheckpointTelemetry]
    epochs_completed: int | None = None
    epochs_note: str = "The native trainer reports steps, not epochs."
