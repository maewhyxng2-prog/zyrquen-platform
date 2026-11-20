import hashlib
import hmac
import ipaddress
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.api_access_models import LoginRateLimit
from apps.api.database import get_db
from apps.api.models import User
from apps.api.schemas import UserRegister, UserLogin, UserResponse
from apps.api.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    oauth2_scheme,
    revoke_access_token,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_BLOCK_DURATION = timedelta(minutes=15)
LOGIN_FAILURE_LIMIT = 5
TRUSTED_PROXY_SETTING = "ZYRQUEN_TRUSTED_PROXY_IPS"
DUMMY_PASSWORD_HASH = hash_password("zyrquen-invalid-login-dummy-password")


def _login_bucket_key(scope: str, value: str) -> str:
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is not configured",
        )
    return hmac.new(
        secret.encode("utf-8"),
        f"{scope}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _trusted_proxy_networks() -> tuple[
    ipaddress.IPv4Network | ipaddress.IPv6Network,
    ...,
]:
    configured = os.getenv(TRUSTED_PROXY_SETTING, "")
    try:
        return tuple(
            ipaddress.ip_network(value.strip(), strict=False)
            for value in configured.split(",")
            if value.strip()
        )
    except ValueError:
        logger.error("Trusted proxy allowlist is invalid")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable",
        ) from None


def _client_ip(request: Request) -> str:
    if request.client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Client address is unavailable",
        )
    try:
        peer = ipaddress.ip_address(request.client.host)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Client address is unavailable",
        ) from None

    trusted_proxies = _trusted_proxy_networks()
    if not any(peer in network for network in trusted_proxies):
        return peer.compressed

    forwarded_for = request.headers.get("x-forwarded-for", "")
    try:
        forwarded_addresses = [
            ipaddress.ip_address(value.strip())
            for value in forwarded_for.split(",")
        ]
        if not forwarded_for or not forwarded_addresses:
            return peer.compressed
    except ValueError:
        return peer.compressed

    chain = [*forwarded_addresses, peer]
    for address in reversed(chain):
        if not any(address in network for network in trusted_proxies):
            return address.compressed
    return forwarded_addresses[0].compressed


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _login_rate_limit_rows(
    db: Session,
    bucket_keys: tuple[str, str],
    now: datetime,
) -> list[LoginRateLimit]:
    db.query(LoginRateLimit).filter(
        LoginRateLimit.window_started_at < now - timedelta(days=1),
        (
            LoginRateLimit.blocked_until.is_(None)
            | (LoginRateLimit.blocked_until <= now)
        ),
    ).delete(synchronize_session=False)

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise SQLAlchemyError("Unsupported database for login rate limiting")

    statement = insert(LoginRateLimit).values(
        [
            {
                "key_hash": key,
                "failed_attempts": 0,
                "window_started_at": now,
            }
            for key in bucket_keys
        ]
    )
    db.execute(
        statement.on_conflict_do_nothing(
            index_elements=[LoginRateLimit.key_hash],
        )
    )
    rows = (
        db.query(LoginRateLimit)
        .filter(LoginRateLimit.key_hash.in_(bucket_keys))
        .order_by(LoginRateLimit.key_hash)
        .with_for_update()
        .all()
    )
    if len(rows) != len(bucket_keys):
        raise SQLAlchemyError("Login rate-limit buckets could not be initialized")

    blocked_untils = [
        _utc(row.blocked_until)
        for row in rows
        if row.blocked_until is not None and _utc(row.blocked_until) > now
    ]
    if blocked_untils:
        retry_after = max(
            1,
            int((max(blocked_untils) - now).total_seconds()),
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="ลองเข้าสู่ระบบมากเกินไป กรุณารอสักครู่แล้วลองใหม่",
            headers={"Retry-After": str(retry_after)},
        )

    for row in rows:
        blocked_until = _utc(row.blocked_until) if row.blocked_until else None
        window_started_at = _utc(row.window_started_at)
        if (
            blocked_until is not None
            or now - window_started_at >= LOGIN_WINDOW
        ):
            row.failed_attempts = 0
            row.window_started_at = now
            row.blocked_until = None
    return rows


def _record_login_failure(
    db: Session,
    rows: list[LoginRateLimit],
    now: datetime,
) -> None:
    for row in rows:
        row.failed_attempts += 1
        if row.failed_attempts >= LOGIN_FAILURE_LIMIT:
            row.blocked_until = now + LOGIN_BLOCK_DURATION
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.error("Login rate-limit storage failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable",
        ) from None


def _record_login_success(
    db: Session,
    rows: list[LoginRateLimit],
    account_bucket_key: str,
    now: datetime,
) -> None:
    for row in rows:
        if row.key_hash == account_bucket_key:
            row.failed_attempts = 0
            row.window_started_at = now
            row.blocked_until = None
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.error("Login rate-limit storage failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable",
        ) from None


@router.post("/register", response_model=UserResponse)
def register(data: UserRegister, db: Session = Depends(get_db)):
    email = data.email.strip().lower()

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )

    user = User(
        email=email,
        password_hash=hash_password(data.password)
    )

    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if db.query(User).filter(User.email == email).first() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            ) from exc
        raise
    db.refresh(user)

    return user


@router.post("/login")
def login(
    data: UserLogin,
    http_request: Request,
    db: Session = Depends(get_db),
):
    email = data.email.strip().lower()
    bucket_keys = (
        _login_bucket_key("account", email),
        _login_bucket_key("ip", _client_ip(http_request)),
    )
    now = datetime.now(timezone.utc)
    try:
        rate_limit_rows = _login_rate_limit_rows(db, bucket_keys, now)
    except HTTPException:
        raise
    except SQLAlchemyError:
        db.rollback()
        logger.error("Login rate-limit lookup failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable",
        ) from None

    try:
        user = db.query(User).filter(User.email == email).first()
    except SQLAlchemyError:
        db.rollback()
        logger.error("Login account lookup failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable",
        ) from None
    password_valid = verify_password(
        data.password,
        user.password_hash if user else DUMMY_PASSWORD_HASH,
    )
    if not user or not password_valid or not user.is_active:
        _record_login_failure(db, rate_limit_rows, now)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    _record_login_success(db, rate_limit_rows, bucket_keys[0], now)

    token = create_access_token(str(user.id))

    return {
        "access_token": token,
        "token_type": "bearer"
    }


@router.get("/me", response_model=UserResponse)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/logout")
def logout(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    revoke_access_token(token, db)
    return {
        "authenticated": False,
        "revoked": True,
    }
