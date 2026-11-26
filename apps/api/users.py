import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.database import get_db
from apps.api.models import User
from apps.api.security import get_current_user
from apps.api.user_schemas import UserProfileResponse, UserProfileUpdate

router = APIRouter(prefix="/users", tags=["User Profiles"])
logger = logging.getLogger(__name__)


def _unavailable(db: Session) -> HTTPException:
    try:
        db.rollback()
    except SQLAlchemyError:
        pass
    logger.error("User profile database operation failed")
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="ระบบจัดเก็บโปรไฟล์ไม่พร้อมใช้งานชั่วคราว",
    )


@router.get("/me", response_model=UserProfileResponse)
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        user = db.get(User, current_user.id)
        if user is None:
            raise HTTPException(status_code=404, detail="ไม่พบบัญชีผู้ใช้")
        return UserProfileResponse.model_validate(user)
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise _unavailable(db) from None


@router.patch("/me", response_model=UserProfileResponse)
def update_my_profile(
    payload: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    email = payload.email.lower()
    try:
        user = db.get(User, current_user.id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        existing = (
            db.query(User)
            .filter(func.lower(User.email) == email, User.id != user.id)
            .first()
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="อีเมลนี้ถูกใช้งานแล้ว",
            )
        user.email = email
        db.add(user)
        db.commit()
        db.refresh(user)
        return UserProfileResponse.model_validate(user)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="อีเมลนี้ถูกใช้งานแล้ว",
        ) from None
    except SQLAlchemyError:
        raise _unavailable(db) from None
