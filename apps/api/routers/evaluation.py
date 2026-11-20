from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.database import get_db
from apps.api.evaluation_models import EvaluationRun
from apps.api.evaluation_service import create_evaluation_run, get_evaluation_run
from apps.api.models import User
from apps.api.evaluation_schemas import (
    EvaluationRunCreate,
    EvaluationRunResponse,
)
from routers.training import require_training_admin

router = APIRouter(prefix="/v1/evaluation", tags=["evaluation"])


def _serialize_run(run: EvaluationRun) -> EvaluationRunResponse:
    return EvaluationRunResponse(
        id=str(run.id),
        model_version=run.model_version,
        checkpoint_id=run.checkpoint_id,
        dataset_id=run.dataset_id,
        dataset_checksum=run.dataset_checksum,
        status=run.status,
        sample_count=run.sample_count,
        token_count=run.token_count,
        metrics=run.metrics or {},
        metadata=run.metadata_json or {},
        error_message=run.error_message,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


@router.post("/runs", response_model=EvaluationRunResponse, status_code=202)
def trigger_evaluation(
    payload: EvaluationRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_training_admin),
) -> EvaluationRunResponse:
    model_root = Path("./models").resolve()
    model_path = (model_root / payload.model_version).resolve()
    if not model_path.is_relative_to(model_root):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid model version",
        )
    if not model_path.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evaluation model artifacts are unavailable",
        )

    run = create_evaluation_run(
        db,
        user_id=current_user.id,
        payload=payload,
    )
    return _serialize_run(run)


@router.get("/runs/{run_id}", response_model=EvaluationRunResponse)
def get_evaluation_status(
    run_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_training_admin),
) -> EvaluationRunResponse:
    run = get_evaluation_run(db, run_id, current_user.id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation run not found",
        )
    return _serialize_run(run)
