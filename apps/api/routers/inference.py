import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.api_access import get_inference_user
from apps.api.database import get_db
from apps.api.models import ConversationMessage, User
from apps.api.usage import (
    complete_inference,
    finish_inference,
    request_fingerprint,
    reserve_inference,
)
from apps.api.usage_models import InferenceUsage
from apps.core.context import InferenceContext
from apps.core.exceptions import InferenceError, ResourceLimitExceeded
from apps.core.native.sft import SFT_FORMAT_VERSION, encode_sft_prompt
from apps.core.runtime import runtime
from apps.core.streaming import StreamingInferenceEngine
from apps.api.routers.conversations import (
    _owned_conversation,
    persist_completed_assistant_message,
)

router = APIRouter(prefix="/v1/native-ai", tags=["ZYRQUEN Native AI"])
logger = logging.getLogger(__name__)
INFERENCE_TIMEOUT_SECONDS = 120


class InferenceRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4096)
    request_id: UUID
    conversation_id: UUID | None = None
    max_tokens: int = Field(default=256, ge=1, le=1024)
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    top_k: int = Field(default=0, ge=0, le=1000)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)


class StreamInferenceRequest(InferenceRequest):
    conversation_id: UUID


def _token_count(text: str) -> int:
    tokenizer = runtime.loader.tokenizer
    if tokenizer is None or not hasattr(tokenizer, "encode"):
        raise TypeError("Native tokenizer does not expose encode()")
    if getattr(runtime.loader, "prompt_format", None) == SFT_FORMAT_VERSION:
        return len(encode_sft_prompt(tokenizer, text))
    return len(tokenizer.encode(text, add_bos=False, add_eos=False))


def _max_context_tokens() -> int:
    max_seq_len = getattr(runtime.loader, "max_seq_len", None)
    if max_seq_len is None:
        cfg = getattr(getattr(runtime.loader, "model", None), "cfg", None)
        max_seq_len = getattr(cfg, "max_seq_len", None)
    if not isinstance(max_seq_len, int) or max_seq_len <= 0:
        raise ValueError("Native model max_seq_len is unavailable")
    return max_seq_len


def _context(request: InferenceRequest, user_id: UUID) -> InferenceContext:
    return InferenceContext(
        user_id=user_id,
        prompt=request.prompt,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        top_k=request.top_k,
        top_p=request.top_p,
        request_id=request.request_id,
    )


def _storage_unavailable(db: Session) -> HTTPException:
    try:
        db.rollback()
    except SQLAlchemyError:
        pass
    logger.error("Native inference storage operation failed")
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="ระบบจัดเก็บข้อมูลการประมวลผลไม่พร้อมใช้งานชั่วคราว",
    )


def _reserve(
    db: Session,
    request: InferenceRequest,
    current_user: User,
    api_key_id: UUID | None = None,
) -> tuple[InferenceUsage, ConversationMessage | None]:
    if request.conversation_id is not None:
        try:
            _owned_conversation(db, request.conversation_id, current_user.id)
        except HTTPException:
            raise
        except SQLAlchemyError:
            raise _storage_unavailable(db) from None
    if not runtime.is_ready():
        health = runtime.get_health_status()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": health.get("runtime_status", "degraded"),
                "detail": "ZYRQUEN Native Model ยังไม่พร้อมใช้งาน",
            },
        )
    try:
        input_tokens = _token_count(request.prompt)
        max_seq_len = _max_context_tokens()
    except Exception:
        logger.error("Native tokenizer or model config is unavailable for usage measurement")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "degraded",
                "detail": "ข้อมูล Token หรือการตั้งค่า Native Model ยังไม่พร้อมใช้งาน",
            },
        ) from None
    if input_tokens > max_seq_len:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Input เกินจำนวน Token ที่ Native Model รองรับ (max_seq_len={max_seq_len})",
        )

    fingerprint = request_fingerprint(
        user_id=current_user.id,
        conversation_id=request.conversation_id,
        prompt=request.prompt,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        top_k=request.top_k,
        top_p=request.top_p,
        api_key_id=api_key_id,
    )
    usage, created = reserve_inference(
        db=db,
        user_id=current_user.id,
        conversation_id=request.conversation_id,
        request_id=request.request_id,
        request_hash=fingerprint,
        input_tokens=input_tokens,
        reserved_tokens=request.max_tokens,
        model_version=getattr(runtime.loader, "model_version", None),
        api_key_id=api_key_id,
    )

    if created:
        return usage, None
    if request.conversation_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="คำขอที่เสร็จแล้วไม่สามารถเล่นซ้ำได้หากไม่มีบทสนทนา",
        )
    try:
        message = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.id == request.request_id,
                ConversationMessage.conversation_id == request.conversation_id,
                ConversationMessage.role == "assistant",
            )
            .first()
        )
    except SQLAlchemyError:
        raise _storage_unavailable(db) from None
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ไม่พบผลลัพธ์ของคำขอที่เสร็จแล้ว",
        )
    return usage, message


async def _run_native(context: InferenceContext) -> tuple[str, int, int]:
    parts: list[str] = []
    input_tokens = 0
    output_tokens = 0
    saw_final = False
    async with asyncio.timeout(INFERENCE_TIMEOUT_SECONDS):
        engine = StreamingInferenceEngine(runtime.loader)
        async for chunk in engine.stream(context):
            if chunk.is_final:
                saw_final = True
                input_tokens = chunk.input_tokens
                output_tokens = chunk.output_tokens
            elif chunk.text:
                parts.append(chunk.text)
    result = "".join(parts)
    if not saw_final:
        raise InferenceError("Native inference ended without a final chunk")
    if not result.strip():
        raise InferenceError("Native Model returned an empty response")
    return result, input_tokens, output_tokens


def _finish_failed(db: Session, usage: InferenceUsage, state: str) -> None:
    try:
        finish_inference(db, usage, state)
    except SQLAlchemyError:
        try:
            db.rollback()
        except SQLAlchemyError:
            pass
        logger.error("Inference usage could not be finalized")


def _commit_success(
    db: Session,
    usage: InferenceUsage,
    request: InferenceRequest,
    current_user: User,
    result: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    if request.conversation_id is not None:
        persist_completed_assistant_message(
            db=db,
            conversation_id=request.conversation_id,
            user_id=current_user.id,
            message_id=request.request_id,
            content=result,
            commit=False,
        )
    complete_inference(db, usage, input_tokens, output_tokens)
    db.commit()


@router.get("/health")
async def native_ai_health():
    return runtime.get_health_status()


@router.post("/infer")
async def native_inference(
    request: InferenceRequest,
    http_request: Request,
    current_user: User = Depends(get_inference_user),
    db: Session = Depends(get_db),
):
    usage, replay = _reserve(
        db,
        request,
        current_user,
        getattr(http_request.state, "api_key_id", None),
    )
    if replay is not None:
        return {
            "status": "success",
            "request_id": str(request.request_id),
            "provider": "ZYRQUEN_NATIVE_CORE",
            "model_version": usage.model_version or getattr(runtime.loader, "model_version", None),
            "result": replay.content,
        }

    context = _context(request, current_user.id)
    try:
        result, input_tokens, output_tokens = await _run_native(context)
        _commit_success(
            db,
            usage,
            request,
            current_user,
            result,
            input_tokens,
            output_tokens,
        )
        return {
            "status": "success",
            "request_id": str(request.request_id),
            "provider": "ZYRQUEN_NATIVE_CORE",
            "model_version": usage.model_version or getattr(runtime.loader, "model_version", None),
            "result": result,
        }
    except asyncio.CancelledError:
        db.rollback()
        _finish_failed(db, usage, "cancelled")
        raise
    except ResourceLimitExceeded:
        db.rollback()
        _finish_failed(db, usage, "failed")
        raise HTTPException(
            status_code=429,
            detail="คำขอเกินขีดจำกัดที่ Native Model รองรับ",
        ) from None
    except (InferenceError, TimeoutError):
        db.rollback()
        _finish_failed(db, usage, "failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Native AI ประมวลผลไม่สำเร็จ",
        ) from None
    except HTTPException:
        db.rollback()
        _finish_failed(db, usage, "failed")
        raise
    except SQLAlchemyError:
        db.rollback()
        _finish_failed(db, usage, "failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ระบบจัดเก็บข้อมูลการประมวลผลไม่พร้อมใช้งานชั่วคราว",
        ) from None


@router.post("/infer/stream")
async def native_inference_stream(
    request: StreamInferenceRequest,
    http_request: Request,
    current_user: User = Depends(get_inference_user),
    db: Session = Depends(get_db),
):
    usage, replay = _reserve(
        db,
        request,
        current_user,
        getattr(http_request.state, "api_key_id", None),
    )
    if replay is not None:
        async def replay_completed():
            yield f"data: {json.dumps({'text': replay.content, 'index': 0, 'is_final': False})}\n\n"
            yield f"data: {json.dumps({'text': '', 'index': 1, 'is_final': True})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(replay_completed(), media_type="text/event-stream")

    context = _context(request, current_user.id)

    async def event_gen():
        output: list[str] = []
        saw_final = False
        input_tokens = 0
        output_tokens = 0
        try:
            async with asyncio.timeout(INFERENCE_TIMEOUT_SECONDS):
                engine = StreamingInferenceEngine(runtime.loader)
                async for chunk in engine.stream(context):
                    if chunk.is_final:
                        saw_final = True
                        input_tokens = chunk.input_tokens
                        output_tokens = chunk.output_tokens
                    elif chunk.text:
                        output.append(chunk.text)
                    payload = {
                        "text": chunk.text,
                        "index": chunk.index,
                        "is_final": chunk.is_final,
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

            if not saw_final:
                _finish_failed(db, usage, "failed")
                yield f"data: {json.dumps({'error': 'Native AI ส่งข้อมูลไม่ครบถ้วน'})}\n\n"
                return

            result = "".join(output)
            if not result.strip():
                _finish_failed(db, usage, "failed")
                yield f"data: {json.dumps({'error': 'Native Model ไม่ได้ส่งคำตอบ'})}\n\n"
                return

            if await http_request.is_disconnected():
                _finish_failed(db, usage, "cancelled")
                return

            try:
                _commit_success(
                    db,
                    usage,
                    request,
                    current_user,
                    result,
                    input_tokens,
                    output_tokens,
                )
            except HTTPException as exc:
                db.rollback()
                _finish_failed(db, usage, "failed")
                error = exc.detail if isinstance(exc.detail, str) else "Inference persistence failed"
                yield f"data: {json.dumps({'error': error})}\n\n"
                return
            except SQLAlchemyError:
                db.rollback()
                _finish_failed(db, usage, "failed")
                yield f"data: {json.dumps({'error': 'ระบบจัดเก็บบทสนทนาไม่พร้อมใช้งานชั่วคราว'})}\n\n"
                return

            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            _finish_failed(db, usage, "cancelled")
            return
        except ResourceLimitExceeded:
            _finish_failed(db, usage, "failed")
            yield f"data: {json.dumps({'error': 'คำขอเกินขีดจำกัดที่ Native Model รองรับ'})}\n\n"
        except (InferenceError, TimeoutError):
            _finish_failed(db, usage, "failed")
            yield f"data: {json.dumps({'error': 'Native AI ประมวลผลไม่สำเร็จ'})}\n\n"
        except Exception:
            _finish_failed(db, usage, "failed")
            logger.error(
                "Native streaming failed request_id=%s user_id=%s",
                request.request_id,
                current_user.id,
            )
            yield f"data: {json.dumps({'error': 'Native AI ประมวลผลไม่สำเร็จ'})}\n\n"
        finally:
            if usage.status == "running":
                _finish_failed(db, usage, "cancelled")

    return StreamingResponse(event_gen(), media_type="text/event-stream")
