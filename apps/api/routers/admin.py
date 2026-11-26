import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.api_access_models import ApiKey, AuditLog
from apps.api.api_access_schemas import (
    AdminAuditEntry,
    AdminOverview,
    AdminUserSummary,
)
from apps.api.database import get_db
from apps.api.models import User
from apps.api.security import get_current_user
from apps.api.usage_models import InferenceUsage
from apps.api.usage_models import UserQuotaPolicy
from apps.core.runtime import runtime

router = APIRouter(prefix="/admin", tags=["Administration"])
logger = logging.getLogger(__name__)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ไม่มีสิทธิ์เข้าถึงส่วนผู้ดูแลระบบ",
        )
    return current_user


def _storage_error() -> HTTPException:
    logger.error("Admin data query failed")
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="ข้อมูลผู้ดูแลระบบไม่พร้อมใช้งานชั่วคราว",
    )


@router.get("/overview", response_model=AdminOverview)
def overview(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        users = db.query(func.count(User.id)).scalar() or 0
        usage = (
            db.query(
                func.count(InferenceUsage.id),
                func.coalesce(func.sum(InferenceUsage.input_tokens), 0),
                func.coalesce(func.sum(InferenceUsage.output_tokens), 0),
            )
            .filter(InferenceUsage.status == "completed")
            .one()
        )
        active_keys = (
            db.query(func.count(ApiKey.id))
            .filter(
                ApiKey.revoked_at.is_(None),
                ApiKey.expires_at > datetime.now(timezone.utc),
            )
            .scalar()
            or 0
        )
        now = datetime.now(timezone.utc)
        configured_policies = (
            db.query(func.count(UserQuotaPolicy.user_id)).scalar() or 0
        )
        active_policies = (
            db.query(func.count(UserQuotaPolicy.user_id))
            .filter(
                or_(
                    and_(
                        UserQuotaPolicy.window_started_at.is_(None),
                        UserQuotaPolicy.window_ends_at.is_(None),
                    ),
                    and_(
                        UserQuotaPolicy.window_started_at <= now,
                        UserQuotaPolicy.window_ends_at > now,
                    ),
                )
            )
            .scalar()
            or 0
        )
        input_tokens = int(usage[1])
        output_tokens = int(usage[2])
        return AdminOverview(
            users=int(users),
            successful_inference_requests=int(usage[0]),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            active_api_keys=int(active_keys),
            configured_quota_policies=int(configured_policies),
            active_quota_policies=int(active_policies),
            native_ai=runtime.get_health_status(),
        )
    except SQLAlchemyError:
        raise _storage_error() from None


@router.get("/users", response_model=list[AdminUserSummary])
def list_users(
    _: User = Depends(require_admin),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return (
            db.query(User)
            .order_by(User.created_at.desc(), User.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
    except SQLAlchemyError:
        raise _storage_error() from None


@router.get("/audit-logs", response_model=list[AdminAuditEntry])
def list_audit_logs(
    _: User = Depends(require_admin),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    try:
        return (
            db.query(AuditLog)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
            .all()
        )
    except SQLAlchemyError:
        raise _storage_error() from None
