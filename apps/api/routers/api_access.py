import hashlib
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.api_access import API_KEY_SCOPE, create_api_key_secret
from apps.api.api_access_models import ApiKey, AuditLog
from apps.api.api_access_schemas import (
    ApiKeyAutoRotateRequest,
    ApiKeyBulkRevokeRequest,
    ApiKeyBulkRevokeResponse,
    ApiKeyCreateRequest,
    ApiKeyCreated,
    ApiKeyDailyUsagePoint,
    ApiKeyMetadata,
    ApiKeyRevoked,
    ApiKeyUsageSummary,
)
from apps.api.database import get_db
from apps.api.models import User
from apps.api.security import get_current_user
from apps.api.usage_models import InferenceUsage

router = APIRouter(prefix="/users/me/api-keys", tags=["API Access"])
logger = logging.getLogger(__name__)


def _database_failure(db: Session) -> HTTPException:
    try:
        db.rollback()
    except SQLAlchemyError:
        pass
    logger.error("API key storage operation failed")
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="ไม่สามารถจัดเก็บ API Key ได้ในขณะนี้",
    )


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _rotate_key_record(
    key: ApiKey,
    db: Session,
    actor_user_id: UUID,
    action: str,
    now: datetime,
) -> str:
    secret = create_api_key_secret()
    key.key_prefix = secret[:12]
    key.key_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    key.last_rotated_at = now
    key.rotation_count = int(key.rotation_count or 0) + 1
    if key.auto_rotate_enabled and key.auto_rotate_interval_days:
        key.next_rotation_at = now + timedelta(days=key.auto_rotate_interval_days)
        min_expiry = now + timedelta(days=key.auto_rotate_interval_days)
        if _as_utc(key.expires_at) < min_expiry:
            key.expires_at = min_expiry
    else:
        key.next_rotation_at = None
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            resource_id=str(key.id),
        )
    )
    return secret


@router.get("", response_model=list[ApiKeyMetadata])
def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        keys = (
            db.query(ApiKey)
            .filter(ApiKey.user_id == current_user.id)
            .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
            .all()
        )
        now = datetime.now(timezone.utc)
        rotated_any = False
        for key in keys:
            if (
                key.revoked_at is None
                and key.auto_rotate_enabled
                and key.auto_rotate_interval_days
                and key.next_rotation_at is not None
                and _as_utc(key.next_rotation_at) <= now
            ):
                _rotate_key_record(key, db, current_user.id, "api_key.auto_rotated", now)
                rotated_any = True
        if rotated_any:
            db.commit()
            for key in keys:
                db.refresh(key)
        return keys
    except SQLAlchemyError:
        raise _database_failure(db) from None


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_api_key(
    data: ApiKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    secret = create_api_key_secret()
    now = datetime.now(timezone.utc)
    next_rotation = (
        now + timedelta(days=data.auto_rotate_interval_days)
        if data.auto_rotate_enabled and data.auto_rotate_interval_days is not None
        else None
    )
    key = ApiKey(
        user_id=current_user.id,
        name=data.name,
        key_prefix=secret[:12],
        key_hash=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
        scope=API_KEY_SCOPE,
        expires_at=data.expires_at.astimezone(timezone.utc),
        auto_rotate_enabled=data.auto_rotate_enabled,
        auto_rotate_interval_days=data.auto_rotate_interval_days,
        next_rotation_at=next_rotation,
        rotation_count=0,
    )
    db.add(key)
    try:
        db.flush()
        db.add(
            AuditLog(
                actor_user_id=current_user.id,
                action="api_key.created",
                resource_id=str(key.id),
            )
        )
        db.commit()
        db.refresh(key)
    except SQLAlchemyError:
        raise _database_failure(db) from None
    return ApiKeyCreated(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        scope=key.scope,
        created_at=key.created_at,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        auto_rotate_enabled=key.auto_rotate_enabled,
        auto_rotate_interval_days=key.auto_rotate_interval_days,
        last_rotated_at=key.last_rotated_at,
        next_rotation_at=key.next_rotation_at,
        rotation_count=key.rotation_count,
        key=secret,
    )


@router.post("/bulk-revoke", response_model=ApiKeyBulkRevokeResponse)
def bulk_revoke_api_keys(
    data: ApiKeyBulkRevokeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unique_ids = list(dict.fromkeys(data.ids))
    try:
        keys = (
            db.query(ApiKey)
            .filter(
                ApiKey.user_id == current_user.id,
                ApiKey.id.in_(unique_ids),
                ApiKey.revoked_at.is_(None),
            )
            .with_for_update()
            .all()
        )
        now = datetime.now(timezone.utc)
        revoked_ids: list[UUID] = []
        for key in keys:
            key.revoked_at = now
            key.auto_rotate_enabled = False
            key.next_rotation_at = None
            revoked_ids.append(key.id)
            db.add(
                AuditLog(
                    actor_user_id=current_user.id,
                    action="api_key.bulk_revoked",
                    resource_id=str(key.id),
                )
            )
        db.commit()
        return ApiKeyBulkRevokeResponse(
            revoked_ids=revoked_ids,
            revoked_count=len(revoked_ids),
        )
    except SQLAlchemyError:
        raise _database_failure(db) from None


@router.patch("/{key_id}/auto-rotate", response_model=ApiKeyMetadata)
def update_api_key_auto_rotate(
    key_id: UUID,
    data: ApiKeyAutoRotateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        key = (
            db.query(ApiKey)
            .filter(ApiKey.id == key_id, ApiKey.user_id == current_user.id)
            .with_for_update()
            .first()
        )
        if key is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ API Key",
            )
        if key.revoked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ไม่สามารถตั้งค่า Auto-rotate ให้ API Key ที่ถูกเพิกถอนแล้ว",
            )
        now = datetime.now(timezone.utc)
        key.auto_rotate_enabled = data.auto_rotate_enabled
        key.auto_rotate_interval_days = data.auto_rotate_interval_days
        key.next_rotation_at = (
            now + timedelta(days=data.auto_rotate_interval_days)
            if data.auto_rotate_enabled and data.auto_rotate_interval_days is not None
            else None
        )
        db.add(
            AuditLog(
                actor_user_id=current_user.id,
                action="api_key.auto_rotate_updated",
                resource_id=str(key.id),
            )
        )
        db.commit()
        db.refresh(key)
        return key
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise _database_failure(db) from None


@router.post("/{key_id}/rotate", response_model=ApiKeyCreated)
def rotate_api_key(
    key_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        key = (
            db.query(ApiKey)
            .filter(ApiKey.id == key_id, ApiKey.user_id == current_user.id)
            .with_for_update()
            .first()
        )
        if key is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ API Key",
            )
        if key.revoked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ไม่สามารถหมุนเวียน API Key ที่ถูกเพิกถอนแล้ว",
            )
        now = datetime.now(timezone.utc)
        secret = _rotate_key_record(key, db, current_user.id, "api_key.rotated", now)
        db.commit()
        db.refresh(key)
        return ApiKeyCreated(
            id=key.id,
            name=key.name,
            key_prefix=key.key_prefix,
            scope=key.scope,
            created_at=key.created_at,
            expires_at=key.expires_at,
            revoked_at=key.revoked_at,
            auto_rotate_enabled=key.auto_rotate_enabled,
            auto_rotate_interval_days=key.auto_rotate_interval_days,
            last_rotated_at=key.last_rotated_at,
            next_rotation_at=key.next_rotation_at,
            rotation_count=key.rotation_count,
            key=secret,
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise _database_failure(db) from None


@router.delete("/{key_id}", response_model=ApiKeyRevoked)
def revoke_api_key(
    key_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        key = (
            db.query(ApiKey)
            .filter(ApiKey.id == key_id, ApiKey.user_id == current_user.id)
            .with_for_update()
            .first()
        )
        if key is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ API Key",
            )
        if key.revoked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="API Key นี้ถูกเพิกถอนแล้ว",
            )
        key.revoked_at = datetime.now(timezone.utc)
        key.auto_rotate_enabled = False
        key.next_rotation_at = None
        db.add(
            AuditLog(
                actor_user_id=current_user.id,
                action="api_key.revoked",
                resource_id=str(key.id),
            )
        )
        db.commit()
        return ApiKeyRevoked(id=key.id, revoked=True)
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise _database_failure(db) from None


@router.get("/{key_id}/usage", response_model=ApiKeyUsageSummary)
def get_api_key_usage(
    key_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        key = (
            db.query(ApiKey)
            .filter(ApiKey.id == key_id, ApiKey.user_id == current_user.id)
            .first()
        )
        if key is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบ API Key",
            )
        usage = (
            db.query(
                func.count(InferenceUsage.id),
                func.coalesce(func.sum(InferenceUsage.input_tokens), 0),
                func.coalesce(func.sum(InferenceUsage.output_tokens), 0),
                func.max(InferenceUsage.completed_at),
            )
            .filter(
                InferenceUsage.api_key_id == key.id,
                InferenceUsage.status == "completed",
            )
            .one()
        )
        input_tokens = int(usage[1])
        output_tokens = int(usage[2])

        today_utc = datetime.now(timezone.utc).date()
        start_date = today_utc - timedelta(days=6)
        window_start = datetime(
            start_date.year,
            start_date.month,
            start_date.day,
            tzinfo=timezone.utc,
        )
        buckets: dict[str, dict[str, int]] = {
            (start_date + timedelta(days=offset)).isoformat(): {
                "successful_requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            }
            for offset in range(7)
        }
        recent_rows = (
            db.query(
                InferenceUsage.completed_at,
                InferenceUsage.created_at,
                InferenceUsage.input_tokens,
                InferenceUsage.output_tokens,
            )
            .filter(
                InferenceUsage.api_key_id == key.id,
                InferenceUsage.status == "completed",
                InferenceUsage.created_at >= window_start,
            )
            .all()
        )
        for completed_at, created_at, in_tok, out_tok in recent_rows:
            ts = _as_utc(completed_at or created_at)
            day_key = ts.date().isoformat()
            if day_key in buckets:
                in_val = int(in_tok or 0)
                out_val = int(out_tok or 0)
                buckets[day_key]["successful_requests"] += 1
                buckets[day_key]["input_tokens"] += in_val
                buckets[day_key]["output_tokens"] += out_val
                buckets[day_key]["total_tokens"] += in_val + out_val

        daily_usage = [
            ApiKeyDailyUsagePoint(
                date=day_key,
                successful_requests=vals["successful_requests"],
                input_tokens=vals["input_tokens"],
                output_tokens=vals["output_tokens"],
                total_tokens=vals["total_tokens"],
            )
            for day_key, vals in buckets.items()
        ]
        return ApiKeyUsageSummary(
            key_id=key.id,
            successful_requests=int(usage[0]),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            updated_at=usage[3],
            daily_usage=daily_usage,
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise _database_failure(db) from None
