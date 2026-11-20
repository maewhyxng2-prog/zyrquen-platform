
"""Database service for ZYRQUEN Ω∞ evaluation runs."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .evaluation_models import EvaluationRun
from .evaluation_schemas import EvaluationRunCreate


def create_evaluation_run(
    db: Session,
    user_id: str,
    payload: EvaluationRunCreate,
) -> EvaluationRun:
    """Create a queued evaluation record."""

    run = EvaluationRun(
        user_id=user_id,
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

    db.add(run)
    db.commit()
    db.refresh(run)

    return run


def get_evaluation_run(
    db: Session,
    run_id: str,
    user_id: str,
    is_admin: bool = False,
) -> EvaluationRun | None:
    """Retrieve a run while enforcing user ownership."""

    statement = select(EvaluationRun).where(
        EvaluationRun.id == run_id
    )

    if not is_admin:
        statement = statement.where(
            EvaluationRun.user_id == user_id
        )

    return db.scalar(statement)


def list_evaluation_runs(
    db: Session,
    user_id: str,
    is_admin: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[EvaluationRun], int]:
    """List evaluation runs with ownership filtering and pagination."""

    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    if offset < 0:
        raise ValueError("offset cannot be negative")

    filters = []

    if not is_admin:
        filters.append(EvaluationRun.user_id == user_id)

    count_statement = select(func.count()).select_from(
        EvaluationRun
    )

    query_statement = select(EvaluationRun)

    if filters:
        count_statement = count_statement.where(*filters)
        query_statement = query_statement.where(*filters)

    total = db.scalar(count_statement) or 0

    query_statement = (
        query_statement
        .order_by(EvaluationRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    items = list(db.scalars(query_statement).all())

    return items, total
