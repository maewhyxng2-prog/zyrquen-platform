
import logging
from threading import Lock

from .exceptions import (
    ModelNotFoundError,
    ModelLoadError,
)
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
                logger.warning(
                    "Native model artifact is not installed"
                )
                self._initialized = False

            except ModelLoadError:
                logger.exception(
                    "Native model initialization failed"
                )
                self._initialized = False

            return self._initialized

    def is_ready(self) -> bool:
        return (
            self._initialized
            and self.loader.is_ready()
        )

    def get_health_status(self) -> dict:
        ready = self.is_ready()

        return {
            "runtime_status": (
                "ready" if ready else "degraded"
            ),
            "native_model_loaded": self.loader.is_ready(),
            "authority": "ZYRQUEN Native AI Core",
            "inference_available": ready,
        }


runtime = NativeRuntime()
