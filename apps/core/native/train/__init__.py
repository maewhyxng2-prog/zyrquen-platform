"""Native training package unifying the training pipeline and stage-aware sampler."""

from apps.core.native.train.StageAwareSampler import (
    StageAwareSampler,
    StageSamplerConfig,
    validate_stage_weights,
)
__all__ = [
    "StageAwareSampler",
    "StageSamplerConfig",
    "validate_stage_weights",
]

try:
    from apps.core.native.train.pipeline import (
        ALLOWED_MIXED_PRECISION,
        STRICT_BLOCK_SIZE,
        STRICT_MAX_BATCH_SIZE,
        STRICT_MAX_SEGMENT_STEPS,
        TokenStreamLimitExceeded,
        TrainConfig,
        _resolve_training_identity,
        _training_resume_identity,
        build_token_stream,
        lr_at,
        perplexity,
        resolve_amp_dtype,
        sample_batch,
        train,
        train_sft,
        validate_strict_resource_limits,
    )

    __all__.extend([
        "ALLOWED_MIXED_PRECISION",
        "STRICT_BLOCK_SIZE",
        "STRICT_MAX_BATCH_SIZE",
        "STRICT_MAX_SEGMENT_STEPS",
        "TokenStreamLimitExceeded",
        "TrainConfig",
        "build_token_stream",
        "lr_at",
        "perplexity",
        "resolve_amp_dtype",
        "sample_batch",
        "train",
        "train_sft",
        "validate_strict_resource_limits",
    ])
except ModuleNotFoundError:
    pass
