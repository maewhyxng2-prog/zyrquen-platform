import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from apps.core.native.config import ZyrquenConfig
from apps.core.native.dataset import SCHEMA as DATASET_SCHEMA
from apps.core.native.dataset import load_split
from apps.core.native.tokenizer import ZyrquenTokenizer
from apps.core.native.train import TrainConfig, build_token_stream, train
from apps.core.training_infrastructure.gpu.provisioner import (
    LocalProvider,
    ProvisioningError,
)
from apps.core.training_infrastructure.gpu.resource_manager import ResourceManager


class TrainingUnavailable(RuntimeError):
    """Raised when required training infrastructure or artifacts are unavailable."""


@dataclass(frozen=True)
class PreparedTraining:
    dataset_dir: Path
    tokenizer_path: Path
    training_root: Path
    dataset_version: str
    training_config: TrainConfig
    model_config: ZyrquenConfig
    tokenizer_fingerprint: str


class TrainingOrchestrator:
    def __init__(
        self,
        *,
        dataset_dir: str | Path | None = None,
        tokenizer_path: str | Path | None = None,
        training_root: str | Path | None = None,
        resource_manager: ResourceManager | None = None,
    ):
        dataset_value = dataset_dir or os.getenv("ZYRQUEN_DATASET_DIR")
        tokenizer_value = tokenizer_path or os.getenv("ZYRQUEN_TOKENIZER_PATH")
        root_value = training_root or os.getenv(
            "ZYRQUEN_TRAINING_ROOT", "/data/training"
        )
        self.dataset_dir = Path(dataset_value).resolve() if dataset_value else None
        self.tokenizer_path = (
            Path(tokenizer_value).resolve() if tokenizer_value else None
        )
        self.training_root = Path(root_value).resolve()
        self.resource_manager = resource_manager or ResourceManager()

    def prepare(
        self,
        *,
        dataset_version: str,
        training_values: dict[str, Any],
        model_values: dict[str, Any],
    ) -> PreparedTraining:
        if self.dataset_dir is None or self.tokenizer_path is None:
            raise TrainingUnavailable(
                "Training dataset and tokenizer paths are not configured."
            )
        if not self.dataset_dir.is_dir():
            raise TrainingUnavailable("Configured training dataset is unavailable.")
        if not self.tokenizer_path.is_file():
            raise TrainingUnavailable("Configured native tokenizer is unavailable.")
        storage_path = self.training_root
        while not storage_path.exists() and storage_path.parent != storage_path:
            storage_path = storage_path.parent
        try:
            mode = storage_path.stat().st_mode
            writable = os.access(storage_path, os.W_OK | os.X_OK)
        except OSError as exc:
            raise TrainingUnavailable(
                "Training artifact storage is unavailable."
            ) from exc
        if not stat.S_ISDIR(mode) or not writable:
            raise TrainingUnavailable(
                "Training artifact storage is not writable."
            )

        try:
            tokenizer = ZyrquenTokenizer.load(self.tokenizer_path)
            manifest = json.loads(
                (self.dataset_dir / "manifest.json").read_text(encoding="utf-8")
            )
            if (
                manifest.get("schema") != DATASET_SCHEMA
                or manifest.get("version") != dataset_version
            ):
                raise TrainingUnavailable(
                    "Dataset manifest is invalid or does not match dataset_version."
                )
            files = manifest.get("files")
            if not isinstance(files, dict):
                raise TrainingUnavailable("Dataset manifest has no split records.")
            for split in ("train", "validation"):
                file_record = files.get(f"{split}.jsonl")
                if (
                    not isinstance(file_record, dict)
                    or not isinstance(file_record.get("documents"), int)
                    or file_record["documents"] < 1
                ):
                    raise TrainingUnavailable(
                        f"Dataset has no documents in the {split} split."
                    )
                if next(load_split(self.dataset_dir, split), None) is None:
                    raise TrainingUnavailable(
                        f"Dataset has no documents in the {split} split."
                    )
        except TrainingUnavailable:
            raise
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as exc:
            raise TrainingUnavailable(
                "Configured dataset or tokenizer failed integrity validation."
            ) from exc

        try:
            training_config = TrainConfig(**training_values)
            model_config = ZyrquenConfig(
                vocab_size=tokenizer.vocab_size,
                **model_values,
            )
        except (TypeError, ValueError) as exc:
            raise TrainingUnavailable(
                f"Training configuration is invalid: {exc}"
            ) from exc
        if training_config.block_size > model_config.max_seq_len:
            raise TrainingUnavailable(
                "Training block_size must not exceed model max_seq_len."
            )

        try:
            LocalProvider(self.resource_manager).provision()
        except ProvisioningError as exc:
            raise TrainingUnavailable(
                "No NVIDIA GPU is attached to this API worker."
            ) from exc

        try:
            import torch
        except ImportError as exc:
            raise TrainingUnavailable(
                "The training runtime requires a CUDA-enabled PyTorch installation."
            ) from exc
        try:
            cuda_available = torch.cuda.is_available()
        except (RuntimeError, OSError) as exc:
            raise TrainingUnavailable("CUDA runtime is unavailable.") from exc
        if not cuda_available:
            raise TrainingUnavailable(
                "An NVIDIA GPU was detected, but PyTorch CUDA is unavailable."
            )

        return PreparedTraining(
            dataset_dir=self.dataset_dir,
            tokenizer_path=self.tokenizer_path,
            training_root=self.training_root,
            dataset_version=dataset_version,
            training_config=training_config,
            model_config=model_config,
            tokenizer_fingerprint=tokenizer.fingerprint(),
        )

    def run(self, run_id: UUID, prepared: PreparedTraining) -> dict:
        import torch

        from apps.core.native.model import ZyrquenModel

        tokenizer = ZyrquenTokenizer.load(prepared.tokenizer_path)
        train_ids = build_token_stream(
            load_split(prepared.dataset_dir, "train"), tokenizer
        )
        validation_ids = build_token_stream(
            load_split(prepared.dataset_dir, "validation"), tokenizer
        )
        block_size = prepared.training_config.block_size
        if len(train_ids) < block_size + 1 or len(validation_ids) < block_size + 1:
            raise TrainingUnavailable(
                "Tokenized dataset splits must contain block_size + 1 tokens."
            )

        run_dir = prepared.training_root / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        model = ZyrquenModel(prepared.model_config)
        return train(
            model,
            train_ids,
            validation_ids,
            prepared.training_config,
            run_dir / "checkpoints",
            run_dir / "metrics.jsonl",
            device="cuda",
            tokenizer_fingerprint=prepared.tokenizer_fingerprint,
            dataset_version=prepared.dataset_version,
        )
