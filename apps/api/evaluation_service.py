
"""Database service for ZYRQUEN Ω∞ evaluation runs."""

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
