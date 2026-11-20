import hashlib
import json
import logging
from threading import RLock
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.database import get_db
from apps.api.models import User
from apps.api.security import get_current_user
from apps.api.usage_models import InferenceUsage, UserQuotaPolicy
from apps.api.usage_schemas import (
    InferenceUsageResponse,
    QuotaResponse,
    UsageSummaryResponse,
)

router = APIRouter(prefix="/users/me", tags=["Usage"])
logger = logging.getLogger(__name__)

INFERENCE_LEASE_SECONDS = 130
_SQLITE_RESERVATION_LOCK = RLock()


def request_fingerprint(
    *,
    user_id: UUID,
    conversation_id: UUID | None,
    prompt: str,
    max_tokens: int,
    temperature: float,
    top_k: int,
    top_p: float,
    api_key_id: UUID | None = None,
) -> str:
    fingerprint_data = {
        "user_id": str(user_id),
        "conversation_id": str(conversation_id) if conversation_id else None,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_k": top_k,
        "top_p": top_p,
    }
    if api_key_id is not None:
        fingerprint_data["api_key_id"] = str(api_key_id)
    canonical = json.dumps(
        fingerprint_data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _database_unavailable(db: Session) -> HTTPException:
    try:
        db.rollback()
    except SQLAlchemyError:
        pass
    logger.error("Inference usage database operation failed")
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "usage_storage_unavailable",
            "message": "ระบบ Usage ไม่พร้อมใช้งานชั่วคราว",
        },
    )


def _window_query(db: Session, user_id: UUID, policy: UserQuotaPolicy | None):
    query = db.query(InferenceUsage).filter(InferenceUsage.user_id == user_id)
    if policy is not None and policy.window_started_at is not None:
        query = query.filter(
            InferenceUsage.created_at >= policy.window_started_at,
            InferenceUsage.created_at < policy.window_ends_at,
        )
    return query


def _expire_stale_reservations(
    db: Session,
    user_id: UUID,
    now: datetime,
    policy: UserQuotaPolicy | None = None,
) -> bool:
    rows = (
        _window_query(db, user_id, policy)
        .filter(
            InferenceUsage.status == "running",
            InferenceUsage.lease_expires_at <= now,
        )
        .with_for_update()
        .order_by(InferenceUsage.request_id.asc())
        .all()
    )
    for row in rows:
        row.status = "failed"
        row.reserved_tokens = 0
        row.completed_at = now
    return bool(rows)


def _window_is_active(policy: UserQuotaPolicy | None, now: datetime) -> bool:
    if policy is None:
        return False
    if policy.window_started_at is None:
        return True
    start = policy.window_started_at
    end = policy.window_ends_at
    if start is None or end is None:
        return False
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return start <= now < end


def _is_expired(timestamp: datetime, now: datetime) -> bool:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp <= now


def _quota_detail(metric: str, used: int, limit: int) -> HTTPException:
    messages = {
        "requests": "ถึงขีดจำกัดจำนวนคำขอ Native AI แล้ว",
        "input_tokens": "ถึงขีดจำกัด Input Tokens แล้ว",
        "output_tokens": "ถึงขีดจำกัด Output Tokens แล้ว",
        "total_tokens": "ถึงขีดจำกัด Total Tokens แล้ว",
    }
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "quota_exceeded",
            "metric": metric,
            "used": used,
            "limit": limit,
            "message": messages[metric],
        },
    )


def _validate_existing(
    existing: InferenceUsage,
    *,
    user_id: UUID,
    conversation_id: UUID | None,
    fingerprint: str,
) -> InferenceUsage:
    if (
        existing.user_id != user_id
        or existing.conversation_id != conversation_id
    ):
        raise HTTPException(status_code=404, detail="ไม่พบคำขอประมวลผล")
    if existing.request_fingerprint != fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request ID นี้ถูกใช้กับคำขออื่นแล้ว",
        )
    if existing.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="คำขอนี้กำลังทำงานหรือสิ้นสุดแล้ว",
        )
    return existing


def _reserve_inference(
    db: Session,
    user_id: UUID,
    conversation_id: UUID | None,
    request_id: UUID,
    request_hash: str,
    input_tokens: int,
    reserved_tokens: int,
    model_version: str | None,
    api_key_id: UUID | None = None,
) -> tuple[InferenceUsage, bool]:
    try:
        now = datetime.now(timezone.utc)

        # Acquire the quota-policy row before any usage/request row. This is
        # the single lock order for every reservation in PostgreSQL and SQLite.
        policy = (
            db.query(UserQuotaPolicy)
            .filter(UserQuotaPolicy.user_id == user_id)
            .with_for_update()
            .first()
        )
        if policy is None:
            existing = (
                db.query(InferenceUsage)
                .filter(InferenceUsage.request_id == request_id)
                .with_for_update()
                .first()
            )
            if existing is not None and (
                existing.user_id != user_id
                or existing.conversation_id != conversation_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="ไม่พบคำขอประมวลผล",
                )
            if existing is not None and existing.request_fingerprint != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Request ID นี้ถูกใช้กับคำขออื่นแล้ว",
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "quota_policy_unavailable",
                    "message": "ยังไม่ได้กำหนดนโยบายโควตา Native AI",
                },
            )

        if not _window_is_active(policy, now):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "quota_policy_inactive",
                    "message": "นโยบายโควตา Native AI ยังไม่อยู่ในช่วงใช้งาน",
                },
            )

        existing = (
            db.query(InferenceUsage)
            .filter(InferenceUsage.request_id == request_id)
            .with_for_update()
            .first()
        )
        if existing is not None:
            if (
                existing.user_id != user_id
                or existing.conversation_id != conversation_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="ไม่พบคำขอประมวลผล",
                )
            if existing.request_fingerprint != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Request ID นี้ถูกใช้กับคำขออื่นแล้ว",
                )
            if (
                existing.status == "running"
                and _is_expired(existing.lease_expires_at, now)
            ):
                existing.status = "failed"
                existing.reserved_tokens = 0
                existing.completed_at = now
                db.commit()
                existing = db.query(InferenceUsage).filter(
                    InferenceUsage.request_id == request_id
                ).first()
            else:
                db.commit()
            return (
                _validate_existing(
                    existing,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    fingerprint=request_hash,
                ),
                False,
            )

        # A terminated process must not retain a reservation indefinitely.
        _expire_stale_reservations(db, user_id, now, policy)

        existing = (
            db.query(InferenceUsage)
            .filter(InferenceUsage.request_id == request_id)
            .with_for_update()
            .first()
        )
        if existing is not None:
            db.commit()
            return (
                _validate_existing(
                    existing,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    fingerprint=request_hash,
                ),
                False,
            )

        rows = _window_query(db, user_id, policy).all()
        completed = [row for row in rows if row.status == "completed"]
        running = [row for row in rows if row.status == "running"]
        successful_requests = len(completed)
        requests_in_use = successful_requests + len(running)
        input_in_use = sum(row.input_tokens for row in completed + running)
        output_in_use = sum(row.output_tokens for row in completed) + sum(
            row.reserved_tokens for row in running
        )
        total_in_use = input_in_use + output_in_use

        if (
            policy.max_requests is not None
            and requests_in_use + 1 > policy.max_requests
        ):
            raise _quota_detail("requests", requests_in_use, policy.max_requests)
        if (
            policy.max_input_tokens is not None
            and input_in_use + input_tokens > policy.max_input_tokens
        ):
            raise _quota_detail(
                "input_tokens",
                input_in_use + input_tokens,
                policy.max_input_tokens,
            )
        if (
            policy.max_output_tokens is not None
            and output_in_use + reserved_tokens > policy.max_output_tokens
        ):
            raise _quota_detail(
                "output_tokens",
                output_in_use + reserved_tokens,
                policy.max_output_tokens,
            )
        if (
            policy.max_total_tokens is not None
            and total_in_use + input_tokens + reserved_tokens
            > policy.max_total_tokens
        ):
            raise _quota_detail(
                "total_tokens",
                total_in_use + input_tokens + reserved_tokens,
                policy.max_total_tokens,
            )

        usage = InferenceUsage(
            user_id=user_id,
            conversation_id=conversation_id,
            api_key_id=api_key_id,
            request_id=request_id,
            request_fingerprint=request_hash,
            model_version=model_version,
            status="running",
            input_tokens=input_tokens,
            output_tokens=0,
            reserved_tokens=reserved_tokens,
            lease_expires_at=now + timedelta(seconds=INFERENCE_LEASE_SECONDS),
        )
        db.add(usage)
        db.commit()
        db.refresh(usage)
        return usage, True
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        try:
            existing = (
                db.query(InferenceUsage)
                .filter(InferenceUsage.request_id == request_id)
                .first()
            )
            if existing is not None:
                return (
                    _validate_existing(
                        existing,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        fingerprint=request_hash,
                    ),
                    False,
                )
        except SQLAlchemyError:
            raise _database_unavailable(db) from None
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="คำขอนี้กำลังถูกประมวลผลอยู่",
        ) from None
    except SQLAlchemyError:
        raise _database_unavailable(db) from None


def reserve_inference(
    db: Session,
    user_id: UUID,
    conversation_id: UUID | None,
    request_id: UUID,
    request_hash: str,
    input_tokens: int,
    reserved_tokens: int,
    model_version: str | None,
    api_key_id: UUID | None = None,
) -> tuple[InferenceUsage, bool]:
    if db.get_bind().dialect.name == "sqlite":
        with _SQLITE_RESERVATION_LOCK:
            return _reserve_inference(
                db=db,
                user_id=user_id,
                conversation_id=conversation_id,
                request_id=request_id,
                request_hash=request_hash,
                input_tokens=input_tokens,
                reserved_tokens=reserved_tokens,
                model_version=model_version,
                api_key_id=api_key_id,
            )
    return _reserve_inference(
        db=db,
        user_id=user_id,
        conversation_id=conversation_id,
        request_id=request_id,
        request_hash=request_hash,
        input_tokens=input_tokens,
        reserved_tokens=reserved_tokens,
        model_version=model_version,
        api_key_id=api_key_id,
    )


def complete_inference(
    db: Session,
    usage: InferenceUsage,
    input_tokens: int,
    output_tokens: int,
) -> None:
    if input_tokens <= 0 or output_tokens <= 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "native_token_metrics_unavailable",
                "message": "ข้อมูล Token จาก Native Tokenizer ยังไม่พร้อมใช้งาน",
            },
        )
    if usage.status != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="คำขอนี้ไม่ได้อยู่ในสถานะกำลังประมวลผล",
        )
    usage.status = "completed"
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.reserved_tokens = 0
    usage.completed_at = datetime.now(timezone.utc)


def finish_inference(
    db: Session,
    usage: InferenceUsage,
    status_value: str,
) -> None:
    if status_value not in {"failed", "cancelled"}:
        raise ValueError("Inference terminal status must be failed or cancelled")
    if usage.status != "running":
        return
    usage.status = status_value
    usage.output_tokens = 0
    usage.reserved_tokens = 0
    usage.completed_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/usage", response_model=UsageSummaryResponse)
def get_my_usage(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        now = datetime.now(timezone.utc)
        rows = (
            db.query(InferenceUsage)
            .filter(InferenceUsage.user_id == current_user.id)
            .order_by(InferenceUsage.created_at.desc())
            .all()
        )
        if _expire_stale_reservations(db, current_user.id, now):
            db.commit()
        successful = [row for row in rows if row.status == "completed"]
        updated_at = max(
            (row.completed_at or row.created_at for row in successful),
            default=None,
        )
        input_tokens = sum(row.input_tokens for row in successful)
        output_tokens = sum(row.output_tokens for row in successful)
        records = [
            InferenceUsageResponse(
                request_id=row.request_id,
                status=row.status,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                total_tokens=row.input_tokens + row.output_tokens,
                model_version=row.model_version,
                created_at=row.created_at,
                completed_at=row.completed_at,
            )
            for row in rows
        ]
        return UsageSummaryResponse(
            successful_requests=len(successful),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            updated_at=updated_at,
            records=records,
        )
    except SQLAlchemyError:
        raise _database_unavailable(db) from None


@router.get("/quota", response_model=QuotaResponse)
def get_my_quota(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        policy = (
            db.query(UserQuotaPolicy)
            .filter(UserQuotaPolicy.user_id == current_user.id)
            .first()
        )
        now = datetime.now(timezone.utc)
        active = _window_is_active(policy, now)
        changed = _expire_stale_reservations(db, current_user.id, now, policy)
        if changed:
            db.commit()
        rows = _window_query(db, current_user.id, policy).all()
        completed = [row for row in rows if row.status == "completed"]
        running = [row for row in rows if row.status == "running"]
        input_tokens = sum(row.input_tokens for row in completed + running)
        output_tokens = sum(row.output_tokens for row in completed) + sum(
            row.reserved_tokens for row in running
        )
        return QuotaResponse(
            configured=policy is not None,
            active=active,
            max_requests=policy.max_requests if policy else None,
            max_input_tokens=policy.max_input_tokens if policy else None,
            max_output_tokens=policy.max_output_tokens if policy else None,
            max_total_tokens=policy.max_total_tokens if policy else None,
            window_started_at=policy.window_started_at if policy else None,
            window_ends_at=policy.window_ends_at if policy else None,
            successful_requests=len(completed),
            running_requests=len(running),
            requests_in_use=len(completed) + len(running),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )
    except SQLAlchemyError:
        raise _database_unavailable(db) from None
