import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from apps.api.database import get_db
from apps.api.models import User
from apps.api.security import get_current_user
from apps.core.native.evaluation import EvaluationEngine
from apps.api.evaluation_models import EvaluationRun

router = APIRouter(prefix="/v1/evaluation", tags=["Evaluation"])

@router.post("/runs")
async def trigger_evaluation(
    model_version: str,
    current_user: User = Depends(get_current_user)
):
    # ในอนาคตสามารถเพิ่มการเช็คสิทธิ์ Admin ตรงนี้ได้
    try:
        engine = EvaluationEngine()
        results = engine.run_evaluation(model_version=model_version)
        return {"message": "Evaluation completed", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/runs/{run_id}")
async def get_evaluation_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found")
    run = db.get(EvaluationRun, run_uuid)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found")
    is_admin = bool(getattr(current_user, "is_admin", False) or getattr(current_user, "role", "") == "admin")
    if not is_admin and run.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
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
