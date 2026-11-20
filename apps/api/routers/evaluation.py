from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from apps.api.database import get_db
from apps.api.models import User
from apps.api.security import get_current_user
from apps.core.native.evaluation import EvaluationEngine

router = APIRouter(prefix="/v1/evaluation", tags=["Evaluation"])

@router.post("/runs")
async def trigger_evaluation(
    model_version: str,
    current_user: User = Depends(get_current_user)
):
    # ในอนาคตสามารถเพิ่มการเช็กสิทธิ์ Admin ตรงนี้ได้
    try:
        engine = EvaluationEngine()
        results = engine.run_evaluation(model_version=model_version)
        return {"message": "Evaluation completed", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
