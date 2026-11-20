import hashlib
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.api_access import API_KEY_SCOPE, create_api_key_secret
from apps.api.api_access_models import ApiKey, AuditLog
from apps.api.api_access_schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreated,
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


@router.get("", response_model=list[ApiKeyMetadata])
def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return (
            db.query(ApiKey)
            .filter(ApiKey.user_id == current_user.id)
            .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
            .all()
        )
    except SQLAlchemyError:
        raise _database_failure(db) from None


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_api_key(
    data: ApiKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    secret = create_api_key_secret()
    key = ApiKey(
        user_id=current_user.id,
        name=data.name,
        key_prefix=secret[:12],
        key_hash=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
        scope=API_KEY_SCOPE,
        expires_at=data.expires_at.astimezone(timezone.utc),
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
        key=secret,
    )


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
        return ApiKeyUsageSummary(
            key_id=key.id,
            successful_requests=int(usage[0]),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            updated_at=usage[3],
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise _database_failure(db) from None
