import json
import uuid
from concurrent.futures import CancelledError
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.core.native.dataset import PrepConfig, Source, prepare_dataset
from apps.core.native.registry import ModelRegistry
from apps.core.native.tokenizer import BASE_VOCAB, ZyrquenTokenizer
from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
    CheckpointManager,
)
from apps.api.database import Base
from apps.api.models import User
from training_jobs import TrainingJobService
from training_models import TrainingRun


def _save_json(state, path):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(state, file)


def _load_json(path):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def _artifacts(tmp_path):
    documents = [
        {"text": f"ZYRQUEN integration test document {index} " * 8}
        for index in range(60)
    ]
    source_path = tmp_path / "source.jsonl"
    source_path.write_text(
        "\n".join(json.dumps(document) for document in documents),
        encoding="utf-8",
    )
    dataset_dir = tmp_path / "dataset"
    prepare_dataset(
        [Source(str(source_path), "integration-test")],
        dataset_dir,
        PrepConfig(val_fraction=0.1, test_fraction=0.1, version="dataset-v1"),
    )
    tokenizer_path = tmp_path / "tokenizer.json"
    ZyrquenTokenizer.train(
        [document["text"] for document in documents],
        BASE_VOCAB + 30,
        version="tokenizer-v1",
    ).save(tokenizer_path)
    return dataset_dir, tokenizer_path


class _TrainingStub:
    def __init__(self, prepared, outcome="success"):
        self.prepared = prepared
        self.outcome = outcome

    def prepare(self, **_kwargs):
        return self.prepared

    def run(self, run_id, prepared):
        if self.outcome == "failed":
            raise RuntimeError("training failed")
        if self.outcome == "cancelled":
            raise CancelledError()

        checkpoint_dir = prepared.training_root / str(run_id) / "checkpoints"
        state = {
            "step": 10,
            "tokenizer_sha256": prepared.tokenizer_fingerprint,
            "dataset_version": prepared.dataset_version,
            "config": {"max_steps": 10},
            "model_config": {"n_layers": 1},
        }
        checkpoint = CheckpointManager(
            checkpoint_dir,
            save_fn=_save_json,
            load_fn=_load_json,
        ).save(10, state)
        if self.outcome == "corrupt_checkpoint":
            checkpoint.write_text("corrupt", encoding="utf-8")
        return {
            "steps": 10,
            "val_loss": 1.25,
            "perplexity": 3.49,
            "stopped_reason": (
                "budget_exceeded" if self.outcome == "early_stop" else None
            ),
        }


@pytest.fixture
def training_env(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'training-registry-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    user_id = uuid.uuid4()
    with session_factory() as db:
        db.add(
            User(
                id=user_id,
                email="registry-admin@example.com",
                password_hash="unused-in-this-test",
            )
        )
        db.commit()

    dataset_dir, tokenizer_path = _artifacts(tmp_path)
    prepared = SimpleNamespace(
        training_root=tmp_path / "training",
        dataset_dir=dataset_dir,
        tokenizer_path=tokenizer_path,
        dataset_version="dataset-v1",
        tokenizer_fingerprint=ZyrquenTokenizer.load(tokenizer_path).fingerprint(),
    )
    registry = ModelRegistry(tmp_path / "registry", load_fn=_load_json)
    yield session_factory, engine, user_id, prepared, registry
    engine.dispose()


def _run_job(training_env, outcome="success"):
    session_factory, _, user_id, prepared, registry = training_env
    service = TrainingJobService(
        session_factory,
        orchestrator=_TrainingStub(prepared, outcome),
        registry=registry,
    )
    try:
        with session_factory() as db:
            run = service.submit(
                db,
                owner_id=user_id,
                dataset_version="dataset-v1",
                training_config={"max_steps": 10},
                model_config={"n_layers": 1},
            )
            run_id = run.id
        service._future.result(timeout=10)
        with session_factory() as db:
            return db.get(TrainingRun, run_id)
    finally:
        service._executor.shutdown(wait=True)


def test_successful_training_registers_verified_lineage(training_env):
    *_, registry = training_env

    run = _run_job(training_env)

    assert run.status == "completed"
    model_version = run.result["model_version"]
    assert model_version == "ZYRQUEN-Native-0.1.0"
    assert run.result["training_run_id"] == str(run.id)
    assert run.result["training_run_id"] != model_version
    record = registry.get(model_version)
    assert registry.verify(model_version)
    assert record["parent"] is None
    assert record["tokenizer"]["version"] == "tokenizer-v1"
    assert record["dataset"]["version"] == "dataset-v1"
    assert record["checkpoint"]["path"] == f"artifacts/{model_version}/checkpoint.pt"
    assert run.result["lineage"] == {
        "model_version": model_version,
        "tokenizer_version": "tokenizer-v1",
        "tokenizer_path": f"artifacts/{model_version}/tokenizer.json",
        "dataset_version": "dataset-v1",
        "dataset_manifest_path": f"artifacts/{model_version}/dataset_manifest.json",
        "checkpoint_path": f"artifacts/{model_version}/checkpoint.pt",
        "checkpoint_sha256": record["checkpoint"]["sha256"],
    }
    assert registry.active_version() is None

    second_run = _run_job(training_env)
    assert second_run.status == "completed"
    assert second_run.result["model_version"] == "ZYRQUEN-Native-0.1.1"
    assert second_run.result["training_run_id"] == str(second_run.id)
    assert registry.get("ZYRQUEN-Native-0.1.1")["parent"] == "ZYRQUEN-Native-0.1.0"
    assert registry.verify("ZYRQUEN-Native-0.1.0")
    assert registry.verify("ZYRQUEN-Native-0.1.1")
    assert registry.active_version() is None


@pytest.mark.parametrize("outcome", ["failed", "cancelled", "early_stop"])
def test_failed_or_cancelled_training_does_not_register(outcome, training_env):
    *_, registry = training_env

    run = _run_job(training_env, outcome)

    assert run.status == "failed"
    assert registry.list_versions() == []
    assert registry.active_version() is None


def test_corrupt_checkpoint_does_not_register(training_env):
    *_, registry = training_env

    run = _run_job(training_env, "corrupt_checkpoint")

    assert run.status == "failed"
    assert "valid integrity" in run.error_message
    assert registry.list_versions() == []
    assert registry.active_version() is None
