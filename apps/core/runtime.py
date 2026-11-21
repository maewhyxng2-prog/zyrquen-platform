import logging
from threading import Lock

from .exceptions import ModelLoadError, ModelNotFoundError
from .inference import NativeInferenceEngine
from .model_loader import NativeModelLoader

logger = logging.getLogger(__name__)


class NativeRuntime:
    def __init__(self, loader=None):
        self.loader = loader or NativeModelLoader()
        self.engine = NativeInferenceEngine(self.loader)

        self._initialized = False
        self._initialization_lock = Lock()

    def initialize(self) -> bool:
        with self._initialization_lock:
            if self.loader.is_ready():
                self._initialized = True
                return True

            try:
                self.loader.load()
                self._initialized = self.loader.is_ready()

            except ModelNotFoundError:
                logger.warning("Native model artifact is not configured or installed")
                self._initialized = False

            except ModelLoadError:
                logger.exception("Native model initialization failed")
                self._initialized = False

            return self._initialized

    def is_ready(self) -> bool:
        return self._initialized and self.loader.is_ready()

    def get_health_status(self) -> dict:
        ready = self.is_ready()
        if ready:
            runtime_status = "ready"
        else:
            health_fn = getattr(self.loader, "health_state", None)
            if callable(health_fn):
                state = health_fn()
                runtime_status = state if state in {"not_configured", "degraded"} else "degraded"
            else:
                model_path = getattr(self.loader, "model_path", None)
                runtime_status = (
                    "not_configured"
                    if (model_path is None or not model_path.is_dir())
                    else "degraded"
                )

        return {
            "runtime_status": runtime_status,
            "native_model_loaded": self.loader.is_ready(),
            "model_version": getattr(self.loader, "model_version", None) if ready else None,
            "artifact_origin": getattr(self.loader, "artifact_origin", None) if ready else None,
            "is_trained": bool(getattr(self.loader, "is_trained", False)) if ready else False,
            "max_seq_len": getattr(self.loader, "max_seq_len", None) if ready else None,
            "authority": "ZYRQUEN Native AI Core",
            "inference_available": ready,
        }

    def shutdown(self) -> None:
        """Release native model resources during application shutdown."""
        with self._initialization_lock:
            self._initialized = False
            unload_fn = getattr(self.loader, "unload", None)
            if callable(unload_fn):
                unload_fn()
            else:
                self.loader.model = None
                self.loader.tokenizer = None


runtime = NativeRuntime()
