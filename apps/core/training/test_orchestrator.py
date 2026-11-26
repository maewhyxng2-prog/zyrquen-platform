import hashlib
import json

import pytest

from apps.core.native.dataset import SCHEMA as DATASET_SCHEMA
from apps.core.native.tokenizer import BASE_VOCAB, ZyrquenTokenizer
from apps.core.training.orchestrator import (
    TrainingOrchestrator,
    TrainingUnavailable,
)


def _write_dataset(path, version="0.1.0"):
    path.mkdir(parents=True)
    files = {}
    for split in ("train", "validation"):
        payload = (
            json.dumps(
                {"text": "ZYRQUEN native training sample text " * 12},
                ensure_ascii=False,
            )
            + "\n"
        )
        content = payload.encode("utf-8")
        (path / f"{split}.jsonl").write_bytes(content)
        files[f"{split}.jsonl"] = {
            "documents": 1,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "schema": DATASET_SCHEMA,
                "version": version,
                "sources": {
                    "declared-source": {
                        "path": "source.jsonl",
                        "license": "CC0-1.0",
                        "sha256": hashlib.sha256(b"declared source").hexdigest(),
                    }
                },
                "files": files,
            }
        ),
        encoding="utf-8",
    )


def _write_tokenizer(path):
    tokenizer = ZyrquenTokenizer.train(
        ["ZYRQUEN native training sample text " * 12],
        BASE_VOCAB,
    )
    tokenizer.save(path)


def _config():
    return {
        "block_size": 8,
        "batch_size": 1,
        "grad_accum_steps": 1,
        "max_steps": 10,
        "lr": 0.001,
        "min_lr": 0.0001,
        "warmup_steps": 0,
        "weight_decay": 0.1,
        "grad_clip": 1.0,
        "eval_interval": 2,
        "eval_batches": 1,
        "checkpoint_interval": 2,
        "log_interval": 1,
        "seed": 1,
    }


def _model_config():
    return {
        "max_seq_len": 16,
        "n_layers": 1,
        "n_heads": 2,
        "d_model": 8,
        "d_ff": 16,
        "dropout": 0.0,
        "rope_theta": 10000.0,
        "norm_eps": 1e-5,
        "tie_embeddings": True,
    }


def test_preflight_accepts_bounded_cpu_training_without_gpu(tmp_path):
    dataset_dir = tmp_path / "dataset"
    tokenizer_path = tmp_path / "tokenizer.json"
    _write_dataset(dataset_dir)
    _write_tokenizer(tokenizer_path)
    orchestrator = TrainingOrchestrator(
        dataset_dir=dataset_dir,
        tokenizer_path=tokenizer_path,
        training_root=tmp_path / "runs",
    )

    prepared = orchestrator.prepare(
        dataset_version="0.1.0",
        training_values=_config(),
        model_values=_model_config(),
    )
    assert prepared.model_config.estimated_num_parameters <= 5_000_000


def test_preflight_rejects_dataset_integrity_failure(tmp_path):
    dataset_dir = tmp_path / "dataset"
    tokenizer_path = tmp_path / "tokenizer.json"
    _write_dataset(dataset_dir)
    _write_tokenizer(tokenizer_path)
    (dataset_dir / "train.jsonl").write_text(
        '{"text":"changed after manifest"}\n',
        encoding="utf-8",
    )
    orchestrator = TrainingOrchestrator(
        dataset_dir=dataset_dir,
        tokenizer_path=tokenizer_path,
        training_root=tmp_path / "runs",
    )

    with pytest.raises(TrainingUnavailable, match="integrity validation"):
        orchestrator.prepare(
            dataset_version="0.1.0",
            training_values=_config(),
            model_values=_model_config(),
        )


def test_preflight_requires_configured_artifact_paths(tmp_path):
    orchestrator = TrainingOrchestrator(
        dataset_dir=None,
        tokenizer_path=None,
        training_root=tmp_path / "runs",
    )

    with pytest.raises(TrainingUnavailable, match="not configured"):
        orchestrator.prepare(
            dataset_version="0.1.0",
            training_values=_config(),
            model_values=_model_config(),
        )


def test_preflight_rejects_non_directory_training_storage(tmp_path):
    dataset_dir = tmp_path / "dataset"
    tokenizer_path = tmp_path / "tokenizer.json"
    training_root = tmp_path / "runs"
    _write_dataset(dataset_dir)
    _write_tokenizer(tokenizer_path)
    training_root.write_text("not a directory", encoding="utf-8")
    orchestrator = TrainingOrchestrator(
        dataset_dir=dataset_dir,
        tokenizer_path=tokenizer_path,
        training_root=training_root,
    )

    with pytest.raises(TrainingUnavailable, match="storage is not writable"):
        orchestrator.prepare(
            dataset_version="0.1.0",
            training_values=_config(),
            model_values=_model_config(),
        )


def test_preflight_rejects_cpu_model_over_parameter_limit(tmp_path):
    dataset_dir = tmp_path / "dataset"
    tokenizer_path = tmp_path / "tokenizer.json"
    _write_dataset(dataset_dir)
    _write_tokenizer(tokenizer_path)
    orchestrator = TrainingOrchestrator(
        dataset_dir=dataset_dir,
        tokenizer_path=tokenizer_path,
        training_root=tmp_path / "runs",
    )

    with pytest.raises(TrainingUnavailable, match="exceeds limit 5000000"):
        orchestrator.prepare(
            dataset_version="0.1.0",
            training_values=_config(),
            model_values={
                **_model_config(),
                "d_model": 1024,
                "n_heads": 8,
                "d_ff": 4096,
                "n_layers": 4,
            },
        )
