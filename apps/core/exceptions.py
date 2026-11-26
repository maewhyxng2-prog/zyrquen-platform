
class ZyrquenRuntimeError(Exception):
    """Base exception for ZYRQUEN Native Runtime."""


class ModelNotFoundError(ZyrquenRuntimeError):
    """Native model artifact is missing."""


class ModelLoadError(ZyrquenRuntimeError):
    """Native model failed to load."""


class InferenceError(ZyrquenRuntimeError):
    """Native inference execution failed."""


class ResourceLimitExceeded(ZyrquenRuntimeError):
    """Inference resource limits were exceeded."""
