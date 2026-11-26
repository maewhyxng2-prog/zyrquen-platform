"""Native training utilities package."""

from apps.core.native.train.StageAwareSampler import (
    StageAwareSampler,
    StageSamplerConfig,
    validate_stage_weights,
)
from apps.core.native.train.trainer import (
    ALLOWED_MIXED_PRECISION,
    STRICT_BLOCK_SIZE,
    STRICT_MAX_BATCH_SIZE,
    STRICT_MAX_SEGMENT_STEPS,
    TrainConfig,
    TokenStreamLimitExceeded,
    build_token_stream,
    lr_at,
    perplexity,
    resolve_amp_dtype,
    sample_batch,
    train,
    train_sft,
    validate_strict_resource_limits,
)

__all__ = [
    "ALLOWED_MIXED_PRECISION",
    "STRICT_BLOCK_SIZE",
    "STRICT_MAX_BATCH_SIZE",
    "STRICT_MAX_SEGMENT_STEPS",
    "StageAwareSampler",
    "StageSamplerConfig",
    "TokenStreamLimitExceeded",
    "TrainConfig",
    "build_token_stream",
    "lr_at",
    "perplexity",
    "resolve_amp_dtype",
    "sample_batch",
    "train",
    "train_sft",
    "validate_stage_weights",
    "validate_strict_resource_limits",
]
