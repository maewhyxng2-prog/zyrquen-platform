
import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.database import get_db
from apps.api.models import User
from apps.api.security import get_current_user

from apps.core.context import InferenceContext
from apps.core.exceptions import (
    InferenceError,
    ResourceLimitExceeded,
)
from apps.core.runtime import runtime
from apps.core.streaming import StreamingInferenceEngine


router = APIRouter(
    prefix="/v1/native-ai",
    tags=["ZYRQUEN Native AI"],
)


class InferenceRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4096)
    max_tokens: int = Field(default=256, ge=1, le=1024)
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    top_k: int = Field(default=0, ge=0, le=1000)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)


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
        top_k=request.top_k,
        top_p=request.top_p,
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

@router.post("/infer/stream")
async def native_inference_stream(
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
        top_k=request.top_k,
        top_p=request.top_p,
    )

    async def event_gen():
        try:
            engine = StreamingInferenceEngine(runtime.loader)
            async for chunk in engine.stream(context):
                payload = {
                    "text": chunk.text,
                    "index": chunk.index,
                    "is_final": chunk.is_final,
                }
                yield f"data: {json.dumps(payload)}\n\n"
            yield "data: [DONE]\n\n"
        except ResourceLimitExceeded as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        except InferenceError:
            yield f"data: {json.dumps({'error': 'Native AI inference failed'})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
    )
