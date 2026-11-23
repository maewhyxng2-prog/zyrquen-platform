
import os
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from apps.api.database import get_db

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login"
)

pwd_context = CryptContext(
    schemes=["bcrypt_sha256", "bcrypt"],
    deprecated="auto",
)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except ValueError:
        return False


def create_access_token(subject: str) -> str:
    secret_key = os.getenv("JWT_SECRET_KEY")

    if not secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is not configured",
        )

    now = datetime.now(timezone.utc)
    expires = now + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": subject,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expires,
    }

    return jwt.encode(
        payload,
        secret_key,
        algorithm=ALGORITHM,
    )


def _decode_and_verify_claims(
    token: str,
    db: Session,
):
    secret_key = os.getenv("JWT_SECRET_KEY")

    if not secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is not configured",
        )

    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[ALGORITHM],
        )

        subject = payload.get("sub")
        jti = payload.get("jti")
        exp = payload.get("exp")

        if not subject or not isinstance(jti, str) or not jti or exp is None:
            raise credentials_error

        user_id = UUID(subject)

    except (InvalidTokenError, ValueError, TypeError):
        raise credentials_error

    from apps.api.models import RevokedToken, User

    revoked = db.query(RevokedToken).filter(
        RevokedToken.jti == jti
    ).first()
    if revoked is not None:
        raise credentials_error

    user = db.query(User).filter(
        User.id == user_id
    ).first()

    if user is None:
        raise credentials_error

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    return user, payload


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    user, _ = _decode_and_verify_claims(token, db)
    return user


def revoke_access_token(
    token: str,
    db: Session,
):
    from apps.api.models import RevokedToken

    user, payload = _decode_and_verify_claims(token, db)
    jti = str(payload["jti"])
    expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)

    existing = db.query(RevokedToken).filter(
        RevokedToken.jti == jti
    ).first()
    if existing is None:
        db.add(
            RevokedToken(
                jti=jti,
                user_id=user.id,
                expires_at=expires_at,
            )
        )
        db.commit()

    return user
