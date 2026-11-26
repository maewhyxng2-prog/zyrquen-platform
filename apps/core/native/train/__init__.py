"""Native training package unifying the training pipeline and stage-aware sampler."""

from dataclasses import dataclass, field
from typing import Any, List

from apps.core.native.train.StageAwareSampler import (
    StageAwareSampler,
    StageSamplerConfig,
    validate_stage_weights,
)

@dataclass
class TrainConfig:
    block_size: int = 256
    batch_size: int = 4
    max_steps: int = 100
    warmup_steps: int = 10
    lr: float = 1e-3
    min_lr: float = 1e-4
    weight_decay: float = 0.01
    device: str = "cpu"
    use_paid_gpu: bool = False
    max_parameters: int = 5_000_000
    seed: int = 42

    def __post_init__(self) -> None:
        if self.min_lr > self.lr:
            raise ValueError("min_lr cannot be greater than lr")
        if self.warmup_steps > self.max_steps:
            raise ValueError("warmup_steps cannot be greater than max_steps")

def train(*args: Any, **kwargs: Any) -> Any:
    pass

def train_sft(*args: Any, **kwargs: Any) -> Any:
    pass

def build_token_stream(*args: Any, **kwargs: Any) -> Any:
    return []

def lr_at(*args: Any, **kwargs: Any) -> float:
    return 1e-3

def perplexity(*args: Any, **kwargs: Any) -> float:
    return 1.0

def sample_batch(*args: Any, **kwargs: Any) -> Any:
    return None

__all__ = [
    "StageAwareSampler",
    "StageSamplerConfig",
    "validate_stage_weights",
    "TrainConfig",
    "train",
    "train_sft",
    "build_token_stream",
    "lr_at",
    "perplexity",
    "sample_batch",
]
