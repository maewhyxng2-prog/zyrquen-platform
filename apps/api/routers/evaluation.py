
"""ZYRQUEN Ω∞ Native Evaluation API."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from evaluation_schemas import (
    EvaluationRunCreate,
    EvaluationRunListResponse,
    EvaluationRunResponse,
)
from evaluation_service import (
    create_evaluation_run,
    get_evaluation_run,
    list_evaluation_runs,
)
from models import User
from security import get_current_user
from training_jobs import training_admin_emails

router = APIRouter(
    prefix="/evaluation",
    tags=["Native Evaluation"],
)


def _is_admin(user: User) -> bool:
    admins = training_admin_emails()
    return (
        bool(admins)
        and user.email.strip().lower() in admins
    )


def _require_admin(user: User) -> User:
    admins = training_admin_emails()

    if not admins:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evaluation admin allowlist is not configured.",
        )

    if user.email.strip().lower() not in admins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Evaluation administrator access is required.",
        )

    return user


def _run_response(run) -> dict:
    return {
        "id": run.id,
        "model_version": run.model_version,
        "checkpoint_id": run.checkpoint_id,
        "dataset_id": run.dataset_id,
        "dataset_checksum": run.dataset_checksum,
        "status": run.status,
        "sample_count": run.sample_count,
        "token_count": run.token_count,
        "metrics": run.metrics or {},
        "metadata": run.metadata_json or {},
        "error_message": run.error_message,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }


@router.post(
    "/runs",
    response_model=EvaluationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_run(
    request: EvaluationRunCreate,
    current_user: User = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    """Create an evaluation record for the authorized administrator."""

    try:
        run = create_evaluation_run(
            db=db,
            user_id=str(current_user.id),
            payload=request,
        )
        return _run_response(run)

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create evaluation run.",
        ) from exc


@router.get(
    "/runs",
    response_model=EvaluationRunListResponse,
)
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List evaluation records owned by the current user."""

    try:
        runs, total = list_evaluation_runs(
            db=db,
            user_id=str(current_user.id),
            is_admin=_is_admin(current_user),
            limit=limit,
            offset=offset,
        )

        return {
            "items": [_run_response(run) for run in runs],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve evaluation runs.",
        ) from exc


@router.get(
    "/runs/{run_id}",
    response_model=EvaluationRunResponse,
)
def get_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve an evaluation run with ownership enforcement."""

    run = get_evaluation_run(
        db=db,
        run_id=run_id,
        user_id=str(current_user.id),
        is_admin=_is_admin(current_user),
    )

    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation run not found.",
        )

    return _run_response(run)
