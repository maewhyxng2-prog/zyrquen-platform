import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from apps.api.api_access_models import ApiKey
from apps.api.database import get_db
from apps.api.models import User
from apps.api.security import _decode_and_verify_claims, oauth2_scheme

API_KEY_PREFIX = "zyr_"
API_KEY_SCOPE = "native:inference"


def api_key_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_api_key_secret() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def get_inference_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not token.startswith(API_KEY_PREFIX):
        request.state.api_key_id = None
        user, _ = _decode_and_verify_claims(token, db)
        return user

    key = db.query(ApiKey).filter(ApiKey.key_hash == api_key_digest(token)).first()
    now = datetime.now(timezone.utc)
    expiry = None
    if key is not None:
        expiry = (
            key.expires_at.replace(tzinfo=timezone.utc)
            if key.expires_at.tzinfo is None
            else key.expires_at.astimezone(timezone.utc)
        )
    if (
        key is None
        or key.revoked_at is not None
        or key.scope != API_KEY_SCOPE
        or expiry is None
        or expiry <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == key.user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.api_key_id = key.id
    return user
