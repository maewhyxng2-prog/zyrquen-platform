
"""Database service for ZYRQUEN Ω∞ evaluation runs."""

from datetime import datetime, timezone
import math
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.evaluation_models import EvaluationRun
from apps.api.evaluation_schemas import EvaluationRunCreate


def _to_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value

    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid UUID value.") from exc


def _validate_metrics_payload(raw_metrics: Any) -> dict[str, float | int]:
    if not isinstance(raw_metrics, dict) or not raw_metrics:
        raise ValueError("Evaluation metrics must be a non-empty JSON object.")
    cleaned: dict[str, float | int] = {}
    for key, val in raw_metrics.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Evaluation metric keys must be non-empty strings.")
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError(f"Evaluation metric {key!r} must be a finite number.")
        if not math.isfinite(float(val)):
            raise ValueError(f"Evaluation metric {key!r} must be finite.")
        cleaned[key] = val
    return cleaned


def create_evaluation_run(
    db: Session,
    user_id: str | UUID,
    payload: EvaluationRunCreate,
) -> EvaluationRun:
    """Create a queued evaluation record."""

    run = EvaluationRun(
        user_id=_to_uuid(user_id),
        model_version=payload.model_version,
        checkpoint_id=payload.checkpoint_id,
        dataset_id=payload.dataset_id,
        dataset_checksum=payload.dataset_checksum.lower(),
        status="queued",
        sample_count=0,
        token_count=0,
        metrics={},
        metadata_json={},
    )

    try:
        db.add(run)
        db.commit()
        db.refresh(run)
    except Exception:
        db.rollback()
        raise

    return run


def mark_evaluation_run_running(
    db: Session,
    run_id: str | UUID,
) -> EvaluationRun:
    """Transition an EvaluationRun record into 'running' state."""
    run = db.get(EvaluationRun, _to_uuid(run_id))
    if run is None:
        raise LookupError(f"Evaluation run not found: {run_id}")
    run.status = "running"
    run.started_at = datetime.now(timezone.utc)
    try:
        db.commit()
        db.refresh(run)
    except Exception:
        db.rollback()
        raise
    return run


def complete_evaluation_run(
    db: Session,
    run_id: str | UUID,
    *,
    results: dict[str, Any],
) -> EvaluationRun:
    """Persist validated evaluation metrics and metadata for a completed run."""
    if not isinstance(results, dict):
        raise ValueError("Evaluation results must be a dictionary.")
    metrics = _validate_metrics_payload(results.get("metrics"))

    run = db.get(EvaluationRun, _to_uuid(run_id))
    if run is None:
        raise LookupError(f"Evaluation run not found: {run_id}")

    splits = results.get("splits") if isinstance(results.get("splits"), dict) else {}
    raw_examples = metrics.get("examples_evaluated")
    if isinstance(raw_examples, (int, float)) and raw_examples >= 0:
        sample_count = int(raw_examples)
    else:
        sample_count = sum(
            int(s.get("evaluated", s.get("total", 0)))
            for s in splits.values()
            if isinstance(s, dict)
        )
    raw_tokens = metrics.get("tokens_evaluated", results.get("token_count", 0))
    token_count = int(raw_tokens) if isinstance(raw_tokens, (int, float)) and not isinstance(raw_tokens, bool) and raw_tokens >= 0 else 0

    metadata: dict[str, Any] = {
        key: results[key]
        for key in (
            "schema",
            "model_version",
            "dataset_version",
            "dataset_content_hash",
            "checkpoint_file",
            "checkpoint_sha256",
            "tokenizer_sha256",
            "inference_status",
            "splits",
            "capability_evaluation",
            "evaluated_at",
        )
        if key in results
    }

    run.status = "completed"
    run.sample_count = max(0, sample_count)
    run.token_count = max(0, token_count)
    run.metrics = metrics
    run.metadata_json = metadata
    run.error_message = None
    run.completed_at = datetime.now(timezone.utc)

    try:
        db.commit()
        db.refresh(run)
    except Exception:
        db.rollback()
        raise
    return run


def fail_evaluation_run(
    db: Session,
    run_id: str | UUID,
    *,
    error_message: str,
    metadata: dict[str, Any] | None = None,
) -> EvaluationRun:
    """Persist 'failed' status and diagnostic reason without fabricating metrics."""
    run = db.get(EvaluationRun, _to_uuid(run_id))
    if run is None:
        raise LookupError(f"Evaluation run not found: {run_id}")

    run.status = "failed"
    run.error_message = str(error_message or "Evaluation failed.")[:2000]
    if isinstance(metadata, dict) and metadata:
        run.metadata_json = {**(run.metadata_json or {}), **metadata}
    run.completed_at = datetime.now(timezone.utc)

    try:
        db.commit()
        db.refresh(run)
    except Exception:
        db.rollback()
        raise
    return run


def get_evaluation_run(
    db: Session,
    run_id: str | UUID,
    user_id: str | UUID,
    is_admin: bool = False,
) -> EvaluationRun | None:
    """Retrieve a run with ownership enforcement."""

    statement = select(EvaluationRun).where(
        EvaluationRun.id == _to_uuid(run_id)
    )

    if not is_admin:
        statement = statement.where(
            EvaluationRun.user_id == _to_uuid(user_id)
        )

    return db.scalar(statement)


def list_evaluation_runs(
    db: Session,
    user_id: str | UUID,
    is_admin: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[EvaluationRun], int]:
    """List evaluation runs with ownership enforcement."""

    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    if offset < 0:
        raise ValueError("offset cannot be negative")

    statement = select(EvaluationRun)
    count_statement = select(func.count()).select_from(
        EvaluationRun
    )

    if not is_admin:
        owner_id = _to_uuid(user_id)
        owner_filter = EvaluationRun.user_id == owner_id
        statement = statement.where(owner_filter)
        count_statement = count_statement.where(owner_filter)

    total = db.scalar(count_statement) or 0

    statement = (
        statement
        .order_by(EvaluationRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    items = list(db.scalars(statement).all())

    return items, total
