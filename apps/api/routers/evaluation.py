from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from apps.api.database import get_db
from apps.api.models import User
from apps.api.security import get_current_user
from apps.api.evaluation_models import EvaluationRun, EvaluationMetric
import os

router = APIRouter(prefix="/v1/evaluation", tags=["Evaluation"])

def is_admin(user: User):
    admin_emails = os.getenv("ZYRQUEN_TRAINING_ADMIN_EMAILS", "").split(",")
    return user.email in admin_emails

@router.post("/runs")
async def trigger_evaluation(
    model_version: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required.")

    if not os.path.exists(f"./models/{model_version}"):
        raise HTTPException(status_code=503, detail="Model artifact not found. Cannot run evaluation.")

    run = EvaluationRun(model_version=model_version, status="pending")
    db.add(run)
    db.commit()
    db.refresh(run)
    return {"message": "Evaluation queued", "run_id": run.id}

@router.get("/runs/{run_id}")
async def get_evaluation_status(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    run = db.query(EvaluationRun).filter(EvaluationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    metrics = {m.metric_name: m.value for m in run.metrics}
    return {"run_id": run.id, "model_version": run.model_version, "status": run.status, "metrics": metrics}
