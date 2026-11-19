
import logging
import os
from pathlib import Path
from threading import Lock

from .exceptions import ModelNotFoundError, ModelLoadError

logger = logging.getLogger(__name__)


class NativeModelLoader:
    def __init__(self, model_path: str | None = None):
        project_root = Path(__file__).resolve().parents[2]

        configured_path = model_path or os.getenv(
            "ZYRQUEN_MODEL_PATH",
            "models/zyrquen-native-v1",
        )

        path = Path(configured_path)

        self.model_path = (
            path if path.is_absolute()
            else project_root / path
        )

        self.model = None
        self.tokenizer = None
        self._load_lock = Lock()

    def load(self):
        with self._load_lock:
            if self.is_ready():
                return

            if not self.model_path.is_dir():
                raise ModelNotFoundError(
                    f"Native model directory not found: {self.model_path}"
                )

            try:
                import torch
                from transformers import (
                    AutoModelForCausalLM,
                    AutoTokenizer,
                )

                tokenizer = AutoTokenizer.from_pretrained(
                    str(self.model_path),
                    local_files_only=True,
                    trust_remote_code=False,
                )

                model = AutoModelForCausalLM.from_pretrained(
                    str(self.model_path),
                    local_files_only=True,
                    trust_remote_code=False,
                )

                device = (
                    "cuda"
                    if torch.cuda.is_available()
                    else "cpu"
                )

                model.to(device)
                model.eval()

                self.tokenizer = tokenizer
                self.model = model

                logger.info(
                    "ZYRQUEN native model loaded on %s",
                    device,
                )

            except Exception as exc:
                self.model = None
                self.tokenizer = None

                logger.exception("Native model loading failed")

                raise ModelLoadError(
                    "Unable to load the native model artifact."
                ) from exc

    def is_ready(self) -> bool:
        return (
            self.model is not None
            and self.tokenizer is not None
        )
