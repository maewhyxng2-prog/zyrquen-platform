
import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from jose import jwt
from passlib.context import CryptContext

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(subject: str) -> str:
    secret_key = os.getenv("JWT_SECRET_KEY")

    if not secret_key:
        raise HTTPException(
            status_code=503,
            detail="Authentication service is not configured",
        )

    expires = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": subject,
        "exp": expires,
    }

    return jwt.encode(
        payload,
        secret_key,
        algorithm=ALGORITHM,
    )
