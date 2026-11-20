import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from apps.core.training.orchestrator import PreparedTraining, TrainingOrchestrator
from apps.core.training.orchestrator import TrainingUnavailable
from training_models import TrainingRun

logger = logging.getLogger(__name__)


class TrainingJobBusy(RuntimeError):
    pass


class TrainingJobService:
    """Single-process dispatcher; job state is persisted in the configured database."""

    def __init__(
        self,
        session_factory: sessionmaker,
        orchestrator: TrainingOrchestrator | None = None,
    ):
        self._session_factory = session_factory
        self._orchestrator = orchestrator or TrainingOrchestrator()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="zyrquen-training"
        )
        self._lock = Lock()
        self._future: Future | None = None
        self._active_run_id: UUID | None = None

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
            self._finish(run_id, status="completed", result=result)
        except Exception as exc:
            logger.exception("Training run %s failed", run_id)
            db.rollback()
            db.close()
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
