import logging
import os
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from apps.core.native.registry import (
    ModelRegistry,
    NativeVersionReservation,
)
from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
    CheckpointManager,
)
from apps.core.training.orchestrator import PreparedTraining, TrainingOrchestrator
from apps.core.training.orchestrator import TrainingUnavailable
from apps.api.training_models import TrainingRun

logger = logging.getLogger(__name__)


class TrainingJobBusy(RuntimeError):
    pass


def allocate_next_native_version(
    registry: ModelRegistry,
) -> tuple[str, str | None]:
    """Compute the next unused ZYRQUEN-Native-MAJOR.MINOR.PATCH candidate safely under lock.

    For concurrent workers that also write to the registry, prefer
    reserve_next_native_version() or registry.register_next_native_version() so the
    chosen version is atomically reserved on disk before registration.
    """
    with registry._registry_lock():
        return registry._next_native_candidate_unlocked(registry._read())


def reserve_next_native_version(
    registry: ModelRegistry,
    *,
    training_run_id: str | None = None,
) -> NativeVersionReservation:
    """Atomically reserve the next unused ZYRQUEN-Native-MAJOR.MINOR.PATCH version."""
    return registry.reserve_next_native_version(training_run_id=training_run_id)


class TrainingJobService:
    """Single-process dispatcher; job state is persisted in the configured database."""

    def __init__(
        self,
        session_factory: sessionmaker,
        orchestrator: TrainingOrchestrator | None = None,
        registry: ModelRegistry | None = None,
    ):
        self._session_factory = session_factory
        self._orchestrator = orchestrator or TrainingOrchestrator()
        self._registry = registry
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="zyrquen-training"
        )
        self._lock = Lock()
        self._future: Future | None = None
        self._active_run_id: UUID | None = None

    def is_busy(self) -> bool:
        with self._lock:
            return self._future is not None and not self._future.done()

    def submit(
        self,
        db: Session,
        *,
        owner_id,
        dataset_version: str,
        training_config: dict,
        model_config: dict,
    ) -> TrainingRun:
        with self._lock:
            if self._future is not None and not self._future.done():
                raise TrainingJobBusy("A training job is already active.")

            prepared = self._orchestrator.prepare(
                dataset_version=dataset_version,
                training_values=training_config,
                model_values=model_config,
            )
            return self._enqueue_prepared_locked(
                db,
                owner_id=owner_id,
                dataset_version=dataset_version,
                training_config=training_config,
                model_config=model_config,
                prepared=prepared,
            )

    def submit_prepared(
        self,
        db: Session,
        *,
        owner_id,
        dataset_version: str,
        training_config: dict,
        model_config: dict,
        prepared: PreparedTraining,
        before_enqueue: Callable[[], Any] | None = None,
    ) -> TrainingRun:
        with self._lock:
            if self._future is not None and not self._future.done():
                raise TrainingJobBusy("A training job is already active.")
            if before_enqueue is not None:
                before_enqueue()
            return self._enqueue_prepared_locked(
                db,
                owner_id=owner_id,
                dataset_version=dataset_version,
                training_config=training_config,
                model_config=model_config,
                prepared=prepared,
            )

    def _enqueue_prepared_locked(
        self,
        db: Session,
        *,
        owner_id,
        dataset_version: str,
        training_config: dict,
        model_config: dict,
        prepared: PreparedTraining,
    ) -> TrainingRun:
        run = TrainingRun(
            owner_id=owner_id,
            status="queued",
            dataset_version=dataset_version,
            training_config=training_config,
            model_config=model_config,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        try:
            self._active_run_id = run.id
            self._future = self._executor.submit(
                self._execute, run.id, prepared
            )
        except RuntimeError as exc:
            self._active_run_id = None
            run.status = "failed"
            run.error_message = "Training worker is unavailable."
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            raise TrainingUnavailable(
                "Training worker is unavailable."
            ) from exc
        return run

    def is_active(self, run_id: UUID) -> bool:
        with self._lock:
            return (
                self._active_run_id == run_id
                and self._future is not None
                and not self._future.done()
            )

    def _execute(self, run_id: UUID, prepared: PreparedTraining) -> None:
        db = self._session_factory()
        registered = False
        try:
            run = db.get(TrainingRun, run_id)
            if run is None:
                logger.error("Training run %s disappeared before execution", run_id)
                db.close()
                return
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            db.commit()
            db.close()

            result = self._orchestrator.run(run_id, prepared)
            if not isinstance(result, dict):
                raise TrainingUnavailable(
                    "Training did not return a valid completion result."
                )
            if result.get("stopped_reason") is not None:
                raise TrainingUnavailable(
                    "Training stopped before successful completion: "
                    f"{result['stopped_reason']}."
                )
            if result.get("parameter_changed") is False:
                raise TrainingUnavailable(
                    "Training completed without modifying model weights."
                )

            checkpoint_dir = prepared.training_root / str(run_id) / "checkpoints"
            if CheckpointManager(checkpoint_dir).latest_valid() is None:
                raise TrainingUnavailable(
                    "Training completed without a checkpoint with valid integrity."
                )

            # Commit successful training before registration. If the process exits
            # before registration, it cannot leave a registry version for a failed run.
            self._finish(run_id, status="completed", result=result)

            registry = self._registry
            if registry is None:
                registry = ModelRegistry(
                    os.getenv(
                        "ZYRQUEN_MODEL_REGISTRY_ROOT", "/data/model-registry"
                    )
                )
                self._registry = registry

            record = registry.register_next_native_version(
                checkpoint_dir,
                prepared.tokenizer_path,
                prepared.dataset_dir,
                metrics=result,
                notes=f"training_run_id={run_id}",
                training_run_id=str(run_id),
            )
            model_version = record["version"]
            registered = True
            result = {
                **result,
                "training_run_id": str(run_id),
                "model_version": model_version,
                "lineage": {
                    "model_version": model_version,
                    "tokenizer_version": record["tokenizer"]["version"],
                    "tokenizer_path": record["tokenizer"]["path"],
                    "dataset_version": record["dataset"]["version"],
                    "dataset_manifest_path": record["dataset"]["path"],
                    "checkpoint_path": record["checkpoint"]["path"],
                    "checkpoint_sha256": record["checkpoint"]["sha256"],
                },
            }
            self._finish(run_id, status="completed", result=result)
        except Exception as exc:
            db.rollback()
            db.close()
            if registered:
                logger.exception(
                    "Training run %s remains completed because its model version "
                    "was registered, but lineage result could not be persisted.",
                    run_id,
                )
                return
            logger.exception("Training run %s failed", run_id)
            self._finish(
                run_id,
                status="failed",
                error_message=f"{type(exc).__name__}: {exc}",
            )

    def _finish(
        self,
        run_id: UUID,
        *,
        status: str,
        result: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._session_factory() as db:
            run = db.get(TrainingRun, run_id)
            if run is None:
                logger.error("Training run %s disappeared during execution", run_id)
                return
            run.status = status
            run.result = result
            run.error_message = error_message
            run.finished_at = datetime.now(timezone.utc)
            db.commit()


def training_admin_emails() -> set[str]:
    return {
        email.strip().lower()
        for email in os.getenv("ZYRQUEN_TRAINING_ADMIN_EMAILS", "").split(",")
        if email.strip()
    }
