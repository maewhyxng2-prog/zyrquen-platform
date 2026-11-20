import json
import math
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
from apps.core.native.train import (
    TokenStreamLimitExceeded,
    TrainConfig,
    build_token_stream,
    train,
)


class TrainingUnavailable(RuntimeError):
    """Raised when required training infrastructure or artifacts are unavailable."""


MAX_CPU_MODEL_PARAMETERS = 5_000_000
MAX_CPU_SEQUENCE_LENGTH = 256
MAX_CPU_BATCH_SIZE = 4
MAX_CPU_GRAD_ACCUM_STEPS = 8
MAX_CPU_TRAINING_STEPS = 1_000
MAX_CPU_EVAL_BATCHES = 20
MAX_CPU_SPLIT_TOKENS = 1_000_000


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
            sources = manifest.get("sources")
            if not isinstance(sources, dict) or not sources:
                raise TrainingUnavailable(
                    "Dataset manifest has no licensed source provenance."
                )
            for source_name, source in sources.items():
                digest = source.get("sha256") if isinstance(source, dict) else None
                license_name = source.get("license") if isinstance(source, dict) else None
                if (
                    not isinstance(license_name, str)
                    or not license_name.strip()
                    or not isinstance(digest, str)
                    or len(digest) != 64
                    or any(char not in "0123456789abcdef" for char in digest)
                ):
                    raise TrainingUnavailable(
                        f"Dataset source provenance is invalid: {source_name}."
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
        if model_config.max_seq_len > MAX_CPU_SEQUENCE_LENGTH:
            raise TrainingUnavailable(
                f"CPU training max_seq_len must be <= {MAX_CPU_SEQUENCE_LENGTH}."
            )
        if model_config.estimated_num_parameters > MAX_CPU_MODEL_PARAMETERS:
            raise TrainingUnavailable(
                "CPU training model exceeds the "
                f"{MAX_CPU_MODEL_PARAMETERS:,}-parameter limit."
            )
        if training_config.batch_size > MAX_CPU_BATCH_SIZE:
            raise TrainingUnavailable(
                f"CPU training batch_size must be <= {MAX_CPU_BATCH_SIZE}."
            )
        if training_config.grad_accum_steps > MAX_CPU_GRAD_ACCUM_STEPS:
            raise TrainingUnavailable(
                "CPU training grad_accum_steps must be <= "
                f"{MAX_CPU_GRAD_ACCUM_STEPS}."
            )
        if training_config.max_steps > MAX_CPU_TRAINING_STEPS:
            raise TrainingUnavailable(
                f"CPU training max_steps must be <= {MAX_CPU_TRAINING_STEPS}."
            )
        if training_config.eval_batches > MAX_CPU_EVAL_BATCHES:
            raise TrainingUnavailable(
                "CPU training eval_batches must be <= "
                f"{MAX_CPU_EVAL_BATCHES}."
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
        try:
            train_ids = build_token_stream(
                load_split(prepared.dataset_dir, "train"),
                tokenizer,
                max_tokens=MAX_CPU_SPLIT_TOKENS,
            )
            validation_ids = build_token_stream(
                load_split(prepared.dataset_dir, "validation"),
                tokenizer,
                max_tokens=MAX_CPU_SPLIT_TOKENS,
            )
        except TokenStreamLimitExceeded as exc:
            raise TrainingUnavailable(
                "Tokenized dataset exceeds the CPU training token limit."
            ) from exc
        block_size = prepared.training_config.block_size
        if len(train_ids) < block_size + 1 or len(validation_ids) < block_size + 1:
            raise TrainingUnavailable(
                "Tokenized dataset splits must contain block_size + 1 tokens."
            )

        run_dir = prepared.training_root / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        model = ZyrquenModel(prepared.model_config)
        result = train(
            model,
            train_ids,
            validation_ids,
            prepared.training_config,
            run_dir / "checkpoints",
            run_dir / "metrics.jsonl",
            tokenizer_fingerprint=prepared.tokenizer_fingerprint,
            dataset_version=prepared.dataset_version,
            cost_controller=_cost_controller_from_env(),
            device="cpu",
        )
        if not result["parameter_changed"]:
            raise TrainingUnavailable(
                "Training completed without changing model parameters."
            )
        if result["train_loss"] is None or result["val_loss"] is None:
            raise TrainingUnavailable(
                "Training did not produce both training and validation loss."
            )
        if not math.isfinite(result["train_loss"]) or not math.isfinite(
            result["val_loss"]
        ):
            raise TrainingUnavailable("Training produced a non-finite loss.")

        from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
            CheckpointManager,
        )

        checkpoints = CheckpointManager(run_dir / "checkpoints")
        checkpoint_entry = checkpoints.latest_valid()
        checkpoint = checkpoints.load_latest()
        if checkpoint_entry is None or checkpoint is None:
            raise TrainingUnavailable(
                "Training did not produce a checkpoint with valid integrity."
            )
        checkpoint_step, state = checkpoint
        if (
            checkpoint_step != result["steps"]
            or state.get("model_config") != prepared.model_config.to_dict()
            or state.get("tokenizer_sha256") != prepared.tokenizer_fingerprint
            or state.get("dataset_version") != prepared.dataset_version
        ):
            raise TrainingUnavailable(
                "Saved checkpoint metadata does not match this training run."
            )

        trained_model = ZyrquenModel(prepared.model_config)
        trained_model.load_state_dict(state["model"])
        if any(
            not torch.equal(state["model"][name], parameter.detach().cpu())
            for name, parameter in model.state_dict().items()
        ):
            raise TrainingUnavailable(
                "Reloaded checkpoint does not contain the final trained parameters."
            )
        trained_model.eval()
        validation_prompt = next(load_split(prepared.dataset_dir, "validation"))
        prompt_ids = tokenizer.encode(validation_prompt)[:block_size]
        if not prompt_ids:
            raise TrainingUnavailable(
                "Validation text produced no tokens for CPU native inference."
            )
        with torch.inference_mode():
            generated_ids = trained_model.generate(
                torch.tensor([prompt_ids], dtype=torch.long),
                max_new_tokens=8,
                temperature=0,
            )
        if generated_ids.shape[1] != len(prompt_ids) + 8:
            raise TrainingUnavailable(
                "Reloaded checkpoint failed native inference verification."
            )
        generated_text = tokenizer.decode(generated_ids[0, len(prompt_ids):].tolist())
        return {
            **result,
            "checkpoint_reloaded": True,
            "checkpoint_sha256": checkpoint_entry["sha256"],
            "inference_verified": True,
            "inference_tokens": 8,
            "inference_text_nonempty": bool(generated_text),
            "device": "cpu",
            "parameter_count": prepared.model_config.estimated_num_parameters,
        }


def _cost_controller_from_env():
    from apps.core.training.cost_limits import cost_controller_from_env

    return cost_controller_from_env()
