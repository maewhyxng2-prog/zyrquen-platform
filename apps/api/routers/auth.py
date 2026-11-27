import base64
import hashlib
import hmac
import ipaddress
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.api_access_models import AuditLog, LoginRateLimit
from apps.api.database import get_db
from apps.api.models import User
from apps.api.schemas import EmailVerifyRequest, UserRegister, UserLogin, UserResponse
from apps.api.security import (
    ALGORITHM,
    _decode_and_verify_claims,
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


def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET_KEY", "").strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is not configured",
        )
    return secret


def _create_signed_verification_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "purpose": "email_verify",
            "sub": str(user.id),
            "email": user.email,
            "iat": now,
            "exp": now + timedelta(hours=24),
        },
        _jwt_secret(),
        algorithm=ALGORITHM,
    )


def _send_verification_email(email: str, token: str, origin: str) -> dict:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("EMAIL_FROM", "").strip()
    if not api_key or not sender:
        return {
            "required": True,
            "emailSent": False,
            "deliveryReason": "EMAIL_PROVIDER_NOT_CONFIGURED",
        }
    clean_origin = origin.rstrip("/")
    verify_url = f"{clean_origin}/login?verify_token={token}"
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": sender,
                "to": [email],
                "subject": "ยืนยันอีเมลสำหรับบัญชี ZYRQUEN ของคุณ",
                "text": (
                    "กรุณาคลิกลิงก์ด้านล่างเพื่อยืนยันอีเมลสำหรับบัญชี ZYRQUEN ของคุณ "
                    f"(ลิงก์มีอายุ 24 ชั่วโมง):\n{verify_url}\n"
                ),
                "html": (
                    "<p>กรุณาคลิกลิงก์ด้านล่างเพื่อยืนยันอีเมลสำหรับบัญชี ZYRQUEN ของคุณ:</p>"
                    f'<p><a href="{verify_url}">Verify Email</a></p>'
                ),
            },
            timeout=10.0,
        )
        if resp.status_code >= 400:
            return {
                "required": True,
                "emailSent": False,
                "deliveryReason": f"EMAIL_PROVIDER_HTTP_{resp.status_code}",
            }
        return {"required": True, "emailSent": True, "deliveryReason": None}
    except httpx.HTTPError:
        return {
            "required": True,
            "emailSent": False,
            "deliveryReason": "EMAIL_SEND_FAILED",
        }


def _oauth_provider_config(provider: str, origin: str) -> dict:
    clean_origin = (origin or "http://localhost:3000").rstrip("/")
    callback_url = f"{clean_origin}/api/backend/auth/oauth/{provider}/callback"
    if provider == "github":
        client_id = os.getenv("GITHUB_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.getenv("GITHUB_OAUTH_CLIENT_SECRET", "").strip()
        return {
            "provider": "github",
            "name": "GitHub",
            "configured": bool(client_id and client_secret),
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": ["read:user", "user:email"],
            "callback_url": callback_url,
            "authorize_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "user_url": "https://api.github.com/user",
            "emails_url": "https://api.github.com/user/emails",
        }
    if provider == "google":
        client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        return {
            "provider": "google",
            "name": "Google",
            "configured": bool(client_id and client_secret),
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": ["openid", "email", "profile"],
            "callback_url": callback_url,
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        }
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unsupported OAuth provider",
    )


def _is_email_verified(db: Session, user_id: uuid.UUID) -> bool:
    return (
        db.query(AuditLog.id)
        .filter(
            AuditLog.actor_user_id == user_id,
            AuditLog.action.in_(["auth.email_verified", "auth.oauth_login"]),
        )
        .first()
        is not None
    )


@router.post("/register", response_model=UserResponse)
def register(
    data: UserRegister,
    http_request: Request,
    db: Session = Depends(get_db),
):
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

    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="user.registered",
            resource_id=str(user.id),
        )
    )
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()

    origin = str(http_request.base_url).rstrip("/")
    try:
        verify_token = _create_signed_verification_token(user)
        _send_verification_email(user.email, verify_token, origin)
    except HTTPException:
        pass

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


@router.get("/me")
def read_current_user(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "role": current_user.role,
        "is_active": current_user.is_active,
        "email_verified": _is_email_verified(db, current_user.id),
    }


@router.post("/verification/resend")
def resend_verification_email(
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if _is_email_verified(db, current_user.id):
        return {
            "ok": True,
            "alreadyVerified": True,
            "email_verified": True,
            "emailSent": False,
            "deliveryReason": None,
        }
    origin = http_request.query_params.get("origin") or str(http_request.base_url).rstrip("/")
    token = _create_signed_verification_token(current_user)
    delivery = _send_verification_email(current_user.email, token, origin)
    db.add(
        AuditLog(
            actor_user_id=current_user.id,
            action="auth.verification_resend",
            resource_id=str(current_user.id),
        )
    )
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
    return {
        "ok": True,
        "alreadyVerified": False,
        "email_verified": False,
        **delivery,
    }


@router.post("/verify-email")
def verify_email(data: EmailVerifyRequest, db: Session = Depends(get_db)):
    try:
        claims = jwt.decode(data.token, _jwt_secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ลิงก์ยืนยันอีเมลไม่ถูกต้องหรือหมดอายุแล้ว",
        ) from None
    if claims.get("purpose") != "email_verify" or not claims.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="โทเคนยืนยันอีเมลไม่ถูกต้อง",
        )
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="โทเคนยืนยันอีเมลไม่ถูกต้อง",
        ) from None
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ไม่พบบัญชีผู้ใช้",
        )
    if not _is_email_verified(db, user.id):
        db.add(
            AuditLog(
                actor_user_id=user.id,
                action="auth.email_verified",
                resource_id=str(user.id),
            )
        )
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
    return {
        "ok": True,
        "email_verified": True,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
            "email_verified": True,
        },
    }


@router.get("/providers")
def list_oauth_providers(http_request: Request):
    origin = http_request.query_params.get("origin") or str(http_request.base_url).rstrip("/")
    google_cfg = _oauth_provider_config("google", origin)
    github_cfg = _oauth_provider_config("github", origin)
    return {
        "providers": {
            "google": {"configured": google_cfg["configured"], "name": "Google"},
            "github": {"configured": github_cfg["configured"], "name": "GitHub"},
        }
    }


@router.get("/oauth/{provider}/url")
def oauth_authorize_url(
    provider: str,
    http_request: Request,
    intent: str = Query(default="login"),
    origin: str = Query(default=""),
    db: Session = Depends(get_db),
):
    normalized_provider = provider.strip().lower()
    resolved_origin = origin or str(http_request.base_url).rstrip("/")
    cfg = _oauth_provider_config(normalized_provider, resolved_origin)
    if not cfg["configured"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ยังไม่ได้ตั้งค่าการเข้าสู่ระบบผ่าน {cfg['name']} OAuth 2.0 ใน Backend นี้",
        )

    link_user_id: str | None = None
    if intent == "link":
        auth_header = http_request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to link an external account",
            )
        claims = _decode_and_verify_claims(auth_header[7:].strip(), db)
        link_user_id = str(claims["sub"])

    code_verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    now = datetime.now(timezone.utc)
    state_token = jwt.encode(
        {
            "purpose": "oauth_state",
            "provider": normalized_provider,
            "intent": "link" if intent == "link" else "login",
            "user_id": link_user_id,
            "redirect_uri": cfg["callback_url"],
            "code_verifier": code_verifier,
            "iat": now,
            "exp": now + timedelta(minutes=10),
        },
        _jwt_secret(),
        algorithm=ALGORITHM,
    )
    query_params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["callback_url"],
        "response_type": "code",
        "scope": " ".join(cfg["scopes"]),
        "state": state_token,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if normalized_provider == "google":
        query_params["prompt"] = "select_account"

    return {
        "url": f"{cfg['authorize_url']}?{urlencode(query_params)}",
        "provider": normalized_provider,
        "callbackUrl": cfg["callback_url"],
    }


@router.get("/oauth/{provider}/callback")
def oauth_callback(
    provider: str,
    http_request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    error_description: str = Query(default=""),
    db: Session = Depends(get_db),
):
    normalized_provider = provider.strip().lower()
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_description or error,
        )
    if not state or not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state or authorization code missing",
        )
    try:
        state_claims = jwt.decode(state, _jwt_secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state ไม่ถูกต้องหรือหมดอายุ",
        ) from None
    if (
        state_claims.get("purpose") != "oauth_state"
        or state_claims.get("provider") != normalized_provider
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state ไม่ตรงกับผู้ให้บริการ",
        )

    cfg = _oauth_provider_config(
        normalized_provider,
        str(http_request.base_url).rstrip("/"),
    )
    if not cfg["configured"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ยังไม่ได้ตั้งค่า {cfg['name']} OAuth 2.0 ใน Backend นี้",
        )

    redirect_uri = str(state_claims.get("redirect_uri") or cfg["callback_url"])
    code_verifier = str(state_claims.get("code_verifier") or "")
    provider_email = ""
    provider_email_verified = False
    provider_user_id = ""

    if normalized_provider == "github":
        token_resp = httpx.post(
            cfg["token_url"],
            headers={"Accept": "application/json"},
            data={
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            timeout=12.0,
        )
        token_json = token_resp.json() if token_resp.content else {}
        gh_access = token_json.get("access_token")
        if token_resp.status_code >= 400 or not gh_access:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=token_json.get("error_description")
                or token_json.get("error")
                or "GitHub token exchange failed",
            )
        gh_headers = {
            "Authorization": f"Bearer {gh_access}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ZYRQUEN-Platform",
        }
        user_resp = httpx.get(cfg["user_url"], headers=gh_headers, timeout=10.0)
        if user_resp.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub user lookup failed",
            )
        gh_user = user_resp.json()
        provider_user_id = str(gh_user.get("id") or "").strip()
        emails_resp = httpx.get(cfg["emails_url"], headers=gh_headers, timeout=10.0)
        if emails_resp.status_code < 400:
            emails = emails_resp.json() or []
            preferred = (
                next((e for e in emails if e.get("primary") and e.get("verified")), None)
                or next((e for e in emails if e.get("verified")), None)
                or next((e for e in emails if e.get("primary")), None)
                or (emails[0] if emails else None)
            )
            if preferred and preferred.get("email"):
                provider_email = str(preferred["email"]).strip().lower()
                provider_email_verified = bool(preferred.get("verified"))
        if not provider_email and gh_user.get("email"):
            provider_email = str(gh_user["email"]).strip().lower()
    else:
        token_resp = httpx.post(
            cfg["token_url"],
            headers={"Accept": "application/json"},
            data={
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
            },
            timeout=12.0,
        )
        token_json = token_resp.json() if token_resp.content else {}
        g_access = token_json.get("access_token")
        if token_resp.status_code >= 400 or not g_access:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=token_json.get("error_description")
                or token_json.get("error")
                or "Google token exchange failed",
            )
        info_resp = httpx.get(
            cfg["userinfo_url"],
            headers={"Authorization": f"Bearer {g_access}", "Accept": "application/json"},
            timeout=10.0,
        )
        if info_resp.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google userinfo lookup failed",
            )
        g_user = info_resp.json()
        provider_user_id = str(g_user.get("sub") or "").strip()
        provider_email = str(g_user.get("email") or "").strip().lower()
        provider_email_verified = bool(g_user.get("email_verified"))

    if not provider_user_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OAuth provider did not return user identifier",
        )

    intent = state_claims.get("intent")
    if intent == "link" and state_claims.get("user_id"):
        target_id = uuid.UUID(str(state_claims["user_id"]))
        target_user = db.query(User).filter(User.id == target_id).first()
        if not target_user or not target_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account disabled",
            )
        db.add(
            AuditLog(
                actor_user_id=target_user.id,
                action="auth.identity_linked",
                resource_id=f"{normalized_provider}:{provider_user_id}"[:64],
            )
        )
        db.commit()
        return {
            "ok": True,
            "intent": "link",
            "provider": normalized_provider,
            "identity": {
                "provider": normalized_provider,
                "provider_user_id": provider_user_id,
                "provider_email": provider_email or None,
                "email_verified": provider_email_verified,
            },
        }

    if not provider_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="OAuth provider account has no email address",
        )
    user = db.query(User).filter(User.email == provider_email).first()
    if user:
        if not provider_email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Verified email required to link existing account",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account disabled",
            )
    else:
        user = User(
            email=provider_email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="auth.oauth_login",
            resource_id=f"{normalized_provider}:{provider_user_id}"[:64],
        )
    )
    db.commit()

    access_token = create_access_token(str(user.id))
    return {
        "ok": True,
        "intent": "login",
        "provider": normalized_provider,
        "access_token": access_token,
        "token_type": "bearer",
        "email": user.email,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
            "email_verified": provider_email_verified or _is_email_verified(db, user.id),
        },
    }


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
