import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.api.database import get_db
from apps.api.evaluation_models import EvaluationRun
from apps.api.evaluation_schemas import EvaluationRunCreate
from apps.api.evaluation_service import list_evaluation_runs
from apps.api.models import User
from apps.api.security import get_current_user
from apps.core.native.evaluation import (
    EvaluationEngine,
    EvaluationEvidenceError,
    EvaluationNotConfiguredError,
)

router = APIRouter(prefix="/v1/evaluation", tags=["Evaluation"])


def _is_admin(user: User) -> bool:
    return bool(
        getattr(user, "is_admin", False)
        or getattr(user, "role", "") == "admin"
    )


def _serialize_run(run: EvaluationRun) -> dict:
    return {
        "id": str(run.id),
        "user_id": str(run.user_id),
        "model_version": run.model_version,
        "checkpoint_id": run.checkpoint_id,
        "dataset_id": run.dataset_id,
        "dataset_checksum": run.dataset_checksum,
        "status": run.status,
        "sample_count": run.sample_count,
        "token_count": run.token_count,
        "metrics": run.metrics,
        "metadata": run.metadata_json,
        "error_message": run.error_message,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }


def _configured_checkpoint_dir() -> Path | None:
    raw = (
        os.getenv("ZYRQUEN_EVALUATION_CHECKPOINT_DIR", "").strip()
        or os.getenv("ZYRQUEN_CHECKPOINT_DIR", "").strip()
    )
    if not raw:
        return None
    path = Path(raw).resolve()
    return path if path.is_dir() else None


def _resolve_dataset_dir(dataset_id: str) -> Path | None:
    raw_root = os.getenv("ZYRQUEN_DATASET_ROOT", "").strip()
    if not raw_root:
        return None
    root = Path(raw_root).resolve()
    if not root.is_dir():
        return None
    candidate = (root / dataset_id).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid dataset_id path",
        )
    return candidate


@router.post("/runs")
async def trigger_evaluation(
    payload: EvaluationRunCreate | None = Body(default=None),
    model_version: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
):
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Evaluation requires a JSON payload with model_version, "
                "dataset_id, and SHA-256 dataset_checksum."
            ),
        )

    checkpoint_dir = _configured_checkpoint_dir()
    dataset_dir = _resolve_dataset_dir(payload.dataset_id)
    if checkpoint_dir is None or dataset_dir is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "not_configured",
                "detail": "Evaluation checkpoint or dataset root directory is not configured.",
            },
        )

    engine = EvaluationEngine(checkpoint_dir=checkpoint_dir)
    try:
        engine.verify_dataset(
            dataset_dir,
            expected_checksum=payload.dataset_checksum,
        )
        engine.verify_checkpoint_version(
            payload.model_version,
            checkpoint_id=payload.checkpoint_id,
        )
        results = engine.run_evaluation(
            payload.model_version,
            dataset_dir=dataset_dir,
            dataset_checksum=payload.dataset_checksum,
        )
        return {"message": "Evaluation completed", "results": results}
    except EvaluationEvidenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except EvaluationNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "not_configured",
                "detail": str(exc),
            },
        ) from exc


@router.get("/runs")
async def list_evaluations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = list_evaluation_runs(
        db,
        user_id=current_user.id,
        is_admin=_is_admin(current_user),
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_serialize_run(run) for run in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/runs/{run_id}")
async def get_evaluation_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation run not found",
        )
    run = db.get(EvaluationRun, run_uuid)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation run not found",
        )
    if not _is_admin(current_user) and run.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )
    return _serialize_run(run)

