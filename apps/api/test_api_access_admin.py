import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from apps.api.api_access import get_inference_user
from apps.api.api_access_models import ApiKey, AuditLog, LoginRateLimit
from apps.api.admin_bootstrap import bootstrap_admin_users
from apps.api.database import Base, get_db
from apps.api.main import app
from apps.api.models import User
from apps.api.routers.auth import _client_ip
from apps.api.usage import request_fingerprint
from apps.api.usage_models import InferenceUsage


@pytest.fixture
def api_access_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api-access.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    def override_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setenv("JWT_SECRET_KEY", "api-access-test-secret")
    monkeypatch.setenv("ZYRQUEN_TRUSTED_PROXY_IPS", "")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    engine.dispose()


def register(client: TestClient, email: str) -> tuple[str, str]:
    result = client.post(
        "/auth/register",
        json={"email": email, "password": "StrongPass123456"},
    )
    assert result.status_code == 200
    user_id = result.json()["id"]
    login = client.post(
        "/auth/login",
        json={"email": email, "password": "StrongPass123456"},
    )
    assert login.status_code == 200
    return user_id, login.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_api_key_create_once_list_revoke_and_owner_isolation(api_access_client):
    client, session_factory = api_access_client
    owner_id, owner_token = register(client, "key-owner@example.com")
    _, other_token = register(client, "key-other@example.com")
    expires_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()

    created = client.post(
        "/users/me/api-keys",
        headers=auth(owner_token),
        json={"name": "  Backend integration  ", "expires_at": expires_at},
    )
    assert created.status_code == 201
    created_data = created.json()
    secret = created_data["key"]
    assert secret.startswith("zyr_")
    assert created_data["name"] == "Backend integration"

    with session_factory() as db:
        row = db.query(ApiKey).one()
        assert row.user_id == uuid.UUID(owner_id)
        assert row.key_hash != secret
        assert row.key_hash == hashlib.sha256(secret.encode()).hexdigest()
        assert db.query(AuditLog).filter_by(action="api_key.created").count() == 1
        request = Request({"type": "http", "headers": []})
        user = get_inference_user(request=request, token=secret, db=db)
        assert user.id == uuid.UUID(owner_id)
        assert request.state.api_key_id == row.id
        db.add(
            InferenceUsage(
                user_id=row.user_id,
                api_key_id=row.id,
                request_id=uuid.uuid4(),
                request_fingerprint="a" * 64,
                status="completed",
                input_tokens=3,
                output_tokens=5,
                reserved_tokens=0,
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
                completed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        with pytest.raises(HTTPException) as expired_key:
            get_inference_user(
                request=Request({"type": "http", "headers": []}),
                token=secret,
                db=db,
            )
        assert expired_key.value.status_code == 401
        row.expires_at = datetime.now(timezone.utc) + timedelta(days=14)
        db.commit()

    listed = client.get("/users/me/api-keys", headers=auth(owner_token))
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "key" not in listed.json()[0]
    assert "key_hash" not in listed.json()[0]

    cross_list = client.get("/users/me/api-keys", headers=auth(other_token))
    assert cross_list.status_code == 200
    assert cross_list.json() == []
    cross_usage = client.get(
        f"/users/me/api-keys/{created_data['id']}/usage",
        headers=auth(other_token),
    )
    assert cross_usage.status_code == 404
    own_usage = client.get(
        f"/users/me/api-keys/{created_data['id']}/usage",
        headers=auth(owner_token),
    )
    assert own_usage.status_code == 200
    assert own_usage.json()["successful_requests"] == 1
    assert own_usage.json()["total_tokens"] == 8
    cross_revoke = client.delete(
        f"/users/me/api-keys/{created_data['id']}",
        headers=auth(other_token),
    )
    assert cross_revoke.status_code == 404

    revoked = client.delete(
        f"/users/me/api-keys/{created_data['id']}",
        headers=auth(owner_token),
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] is True
    with session_factory() as db:
        with pytest.raises(HTTPException) as invalid_key:
            get_inference_user(
                request=Request({"type": "http", "headers": []}),
                token=secret,
                db=db,
            )
        assert invalid_key.value.status_code == 401
        row = db.query(ApiKey).one()
        assert row.revoked_at is not None
        assert db.query(AuditLog).filter_by(action="api_key.revoked").count() == 1


def test_api_key_validation_and_admin_server_side_role(
    api_access_client,
    monkeypatch,
):
    client, session_factory = api_access_client
    user_id, token = register(client, "role-owner@example.com")
    invalid_expiry = client.post(
        "/users/me/api-keys",
        headers=auth(token),
        json={
            "name": "invalid",
            "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        },
    )
    assert invalid_expiry.status_code == 422
    forbidden_role_update = client.patch(
        "/users/me",
        headers=auth(token),
        json={"email": "role-owner@example.com", "role": "admin"},
    )
    assert forbidden_role_update.status_code == 422

    admin_routes = (
        "/admin/overview",
        "/admin/users",
        "/admin/audit-logs",
    )
    for route in admin_routes:
        assert client.get(route, headers=auth(token)).status_code == 403

    monkeypatch.setenv("ZYRQUEN_ADMIN_USER_IDS", user_id)
    with session_factory() as db:
        assert bootstrap_admin_users(db) == 1

    overview = client.get("/admin/overview", headers=auth(token))
    assert overview.status_code == 200
    assert overview.json()["users"] == 1
    assert overview.json()["successful_inference_requests"] == 0
    assert overview.json()["active_api_keys"] == 0
    users = client.get("/admin/users", headers=auth(token))
    assert users.status_code == 200
    assert users.json()[0]["email"] == "role-owner@example.com"
    assert "password_hash" not in users.json()[0]
    audit_logs = client.get("/admin/audit-logs", headers=auth(token))
    assert audit_logs.status_code == 200


def test_admin_bootstrap_uses_trusted_user_ids_only(api_access_client, monkeypatch):
    client, session_factory = api_access_client
    user_id, token = register(client, "bootstrap@example.com")

    with session_factory() as db:
        user = db.get(User, uuid.UUID(user_id))
        assert user is not None
        assert user.role == "user"

    monkeypatch.setenv("ZYRQUEN_ADMIN_USER_IDS", user_id)

    with session_factory() as db:
        assert bootstrap_admin_users(db) == 1

    assert client.get("/admin/overview", headers=auth(token)).status_code == 200


def test_login_rate_limit_is_backend_enforced_and_non_enumerating(api_access_client):
    client, _ = api_access_client
    for _ in range(5):
        response = client.post(
            "/auth/login",
            json={"email": "missing@example.com", "password": "WrongPassword123"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"

    limited = client.post(
        "/auth/login",
        json={"email": "missing@example.com", "password": "WrongPassword123"},
    )
    assert limited.status_code == 429
    assert limited.headers["retry-after"]


def test_login_failure_message_does_not_reveal_account_existence(api_access_client):
    client, _ = api_access_client
    _, token = register(client, "known-account@example.com")
    assert token

    known_account = client.post(
        "/auth/login",
        json={
            "email": "known-account@example.com",
            "password": "WrongPassword123",
        },
    )
    unknown_account = client.post(
        "/auth/login",
        json={
            "email": "unknown-account@example.com",
            "password": "WrongPassword123",
        },
    )
    assert known_account.status_code == unknown_account.status_code == 401
    assert known_account.json() == unknown_account.json()


def test_login_rate_limit_is_global_by_ip_and_expires(api_access_client):
    client, session_factory = api_access_client
    register(client, "valid-account@example.com")
    for index in range(4):
        response = client.post(
            "/auth/login",
            json={
                "email": f"missing-{index}@example.com",
                "password": "WrongPassword123",
            },
        )
        assert response.status_code == 401

    valid_login = client.post(
        "/auth/login",
        json={
            "email": "valid-account@example.com",
            "password": "StrongPass123456",
        },
    )
    assert valid_login.status_code == 200
    fifth_failure = client.post(
        "/auth/login",
        json={"email": "missing-4@example.com", "password": "WrongPassword123"},
    )
    assert fifth_failure.status_code == 401

    limited = client.post(
        "/auth/login",
        json={"email": "another-name@example.com", "password": "WrongPassword123"},
    )
    assert limited.status_code == 429
    assert limited.json()["detail"] == (
        "ลองเข้าสู่ระบบมากเกินไป กรุณารอสักครู่แล้วลองใหม่"
    )

    with session_factory() as db:
        for row in db.query(LoginRateLimit).all():
            if row.blocked_until is not None:
                row.blocked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    after_expiry = client.post(
        "/auth/login",
        json={"email": "another-name@example.com", "password": "WrongPassword123"},
    )
    assert after_expiry.status_code == 401


def test_login_rate_limit_is_per_account_across_client_ips(
    api_access_client,
    monkeypatch,
):
    client, _ = api_access_client
    monkeypatch.setenv("ZYRQUEN_TRUSTED_PROXY_IPS", "127.0.0.1")
    for index in range(5):
        response = client.post(
            "/auth/login",
            headers={"X-Forwarded-For": f"198.51.100.{index + 1}"},
            json={
                "email": "same-account@example.com",
                "password": "WrongPassword123",
            },
        )
        assert response.status_code == 401

    limited = client.post(
        "/auth/login",
        headers={"X-Forwarded-For": "198.51.100.20"},
        json={
            "email": "same-account@example.com",
            "password": "WrongPassword123",
        },
    )
    assert limited.status_code == 429


def test_forwarded_ip_is_used_only_for_allowlisted_proxies(monkeypatch):
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-forwarded-for", b"198.51.100.40")],
            "client": ("192.0.2.10", 1234),
        }
    )
    monkeypatch.setenv("ZYRQUEN_TRUSTED_PROXY_IPS", "")
    assert _client_ip(request) == "192.0.2.10"

    trusted_request = Request(
        {
            "type": "http",
            "headers": [
                (b"x-forwarded-for", b"198.51.100.40, 10.1.0.5")
            ],
            "client": ("10.1.0.6", 1234),
        }
    )
    monkeypatch.setenv("ZYRQUEN_TRUSTED_PROXY_IPS", "10.0.0.0/8")
    assert _client_ip(trusted_request) == "198.51.100.40"


def test_api_key_fingerprint_preserves_session_retry_semantics():
    request_data = {
        "user_id": uuid.uuid4(),
        "conversation_id": None,
        "prompt": "hello",
        "max_tokens": 8,
        "temperature": 0.0,
        "top_k": 0,
        "top_p": 1.0,
    }
    original = request_fingerprint(**request_data)
    session_retry = request_fingerprint(**request_data, api_key_id=None)
    keyed_request = request_fingerprint(**request_data, api_key_id=uuid.uuid4())
    assert original == session_retry
    assert keyed_request != original


def test_api_key_bulk_revoke_and_owner_isolation(api_access_client):
    client, session_factory = api_access_client
    _, owner_token = register(client, "bulk-owner@example.com")
    _, other_token = register(client, "bulk-other@example.com")
    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    k1 = client.post(
        "/users/me/api-keys",
        headers=auth(owner_token),
        json={
            "name": "bulk-k1",
            "expires_at": expires_at,
            "auto_rotate_enabled": True,
            "auto_rotate_interval_days": 15,
        },
    )
    k2 = client.post(
        "/users/me/api-keys",
        headers=auth(owner_token),
        json={"name": "bulk-k2", "expires_at": expires_at},
    )
    other_k = client.post(
        "/users/me/api-keys",
        headers=auth(other_token),
        json={"name": "other-k", "expires_at": expires_at},
    )
    assert k1.status_code == 201 and k2.status_code == 201 and other_k.status_code == 201

    k1_id = k1.json()["id"]
    k2_id = k2.json()["id"]
    other_id = other_k.json()["id"]

    res = client.post(
        "/users/me/api-keys/bulk-revoke",
        headers=auth(owner_token),
        json={"ids": [k1_id, k2_id, other_id, k1_id]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["revoked_count"] == 2
    assert set(body["revoked_ids"]) == {k1_id, k2_id}

    owner_keys = client.get("/users/me/api-keys", headers=auth(owner_token)).json()
    for item in owner_keys:
        assert item["revoked_at"] is not None
        assert item["auto_rotate_enabled"] is False
        assert item["next_rotation_at"] is None

    other_keys = client.get("/users/me/api-keys", headers=auth(other_token)).json()
    assert len(other_keys) == 1
    assert other_keys[0]["revoked_at"] is None

    with session_factory() as db:
        assert db.query(AuditLog).filter_by(action="api_key.bulk_revoked").count() == 2

