
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import User
from security import get_current_user

from apps.core.context import InferenceContext
from apps.core.exceptions import (
    InferenceError,
    ResourceLimitExceeded,
)
from apps.core.runtime import runtime


router = APIRouter(
    prefix="/v1/native-ai",
    tags=["ZYRQUEN Native AI"],
)


class InferenceRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4096)
    max_tokens: int = Field(default=256, ge=1, le=1024)
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)


@router.get("/health")
async def native_ai_health():
    return runtime.get_health_status()


@router.post("/infer")
async def native_inference(
    request: InferenceRequest,
    current_user: User = Depends(get_current_user),
):
    if not runtime.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ZYRQUEN Native Model is not available",
        )

    context = InferenceContext(
        user_id=current_user.id,
        prompt=request.prompt,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
    )

    try:
        result = await runtime.engine.execute(context)

        return {
            "status": "success",
            "request_id": str(context.request_id),
            "provider": "ZYRQUEN_NATIVE_CORE",
            "result": result,
        }

    except ResourceLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        )

    except InferenceError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Native AI inference failed",
        )
