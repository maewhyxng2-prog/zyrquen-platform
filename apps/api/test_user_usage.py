import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from apps.api.database import Base, get_db
from apps.api.main import app
from apps.api.models import Conversation, User
from apps.api.usage import (
    complete_inference,
    finish_inference,
    request_fingerprint,
    reserve_inference,
)
from apps.api.usage_models import InferenceUsage, UserQuotaPolicy


@pytest.fixture
def profile_usage_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'profile-usage.db'}",
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

    monkeypatch.setenv("JWT_SECRET_KEY", "profile-usage-test-secret")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    engine.dispose()


def register(client: TestClient, email: str) -> tuple[str, str]:
    registered = client.post(
        "/auth/register",
        json={"email": email, "password": "StrongPass123456"},
    )
    assert registered.status_code == 200
    login = client.post(
        "/auth/login",
        json={"email": email, "password": "StrongPass123456"},
    )
    assert login.status_code == 200
    return registered.json()["id"], login.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_profile_get_patch_and_cross_user_access(profile_usage_client):
    client, _ = profile_usage_client
    user_id, token = register(client, "Profile@Example.com")
    headers = auth(token)

    me = client.get("/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["id"] == user_id
    assert me.json()["email"] == "profile@example.com"

    updated = client.patch(
        "/users/me",
        headers=headers,
        json={"email": "New.Profile@Example.com"},
    )
    assert updated.status_code == 200
    assert updated.json()["email"] == "new.profile@example.com"

    _, other_token = register(client, "other@example.com")
    conflict = client.patch(
        "/users/me",
        headers=auth(other_token),
        json={"email": "new.profile@example.com"},
    )
    assert conflict.status_code == 409
    forbidden = client.patch(
        "/users/me",
        headers=headers,
        json={"email": "valid@example.com", "id": user_id, "is_active": False},
    )
    assert forbidden.status_code == 422
    invalid_email = client.patch(
        "/users/me",
        headers=headers,
        json={"email": "not-an-email"},
    )
    assert invalid_email.status_code == 422

    assert client.get("/users/me").status_code == 401
    assert client.patch("/users/me", json={"email": "bad@example.com"}).status_code == 401


def test_usage_and_quota_fail_closed_without_policy(profile_usage_client):
    client, session_factory = profile_usage_client
    user_id, token = register(client, "quota@example.com")
    headers = auth(token)

    quota = client.get("/users/me/quota", headers=headers)
    usage = client.get("/users/me/usage", headers=headers)
    assert quota.status_code == 200
    assert quota.json()["configured"] is False
    assert usage.status_code == 200
    assert usage.json()["successful_requests"] == 0

    with session_factory() as db:
        with pytest.raises(HTTPException) as unavailable:
            reserve_inference(
                db=db,
                user_id=uuid.UUID(user_id),
                conversation_id=None,
                request_id=uuid.uuid4(),
                request_hash="a" * 64,
                input_tokens=1,
                reserved_tokens=1,
                model_version=None,
            )
        assert unavailable.value.status_code == 503
        assert unavailable.value.detail["code"] == "quota_policy_unavailable"
        user = db.get(User, uuid.UUID(user_id))
        conversation = Conversation(user_id=user.id, title="Quota")
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        conversation_id = conversation.id

    response = client.post(
        "/v1/native-ai/infer/stream",
        headers=headers,
        json={
            "prompt": "hello",
            "conversation_id": str(conversation_id),
            "request_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 503


def test_usage_retry_is_idempotent_and_quota_excludes_failed(profile_usage_client):
    client, session_factory = profile_usage_client
    user_id, token = register(client, "usage@example.com")
    headers = auth(token)

    with session_factory() as db:
        user_id_uuid = uuid.UUID(user_id)
        conversation = Conversation(user_id=user_id_uuid, title="Usage")
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        db.add(
            UserQuotaPolicy(
                user_id=user_id_uuid,
                max_requests=2,
                max_input_tokens=100,
                max_output_tokens=100,
                max_total_tokens=200,
            )
        )
        db.commit()
        conversation_id = conversation.id

    request_id = uuid.uuid4()
    fingerprint = request_fingerprint(
        user_id=uuid.UUID(user_id),
        conversation_id=conversation_id,
        prompt="hello",
        max_tokens=20,
        temperature=0.7,
        top_k=0,
        top_p=1.0,
    )
    with session_factory() as db:
        usage, created = reserve_inference(
            db=db,
            user_id=uuid.UUID(user_id),
            conversation_id=conversation_id,
            request_id=request_id,
            request_hash=fingerprint,
            input_tokens=10,
            reserved_tokens=20,
            model_version=None,
        )
        assert created is True
        complete_inference(db, usage, input_tokens=10, output_tokens=20)
        db.commit()
        replay, created = reserve_inference(
            db=db,
            user_id=uuid.UUID(user_id),
            conversation_id=conversation_id,
            request_id=request_id,
            request_hash=fingerprint,
            input_tokens=10,
            reserved_tokens=20,
            model_version=None,
        )
        assert created is False
        assert replay.id == usage.id
        with pytest.raises(HTTPException) as mismatch:
            reserve_inference(
                db=db,
                user_id=uuid.UUID(user_id),
                conversation_id=conversation_id,
                request_id=request_id,
                request_hash="d" * 64,
                input_tokens=10,
                reserved_tokens=20,
                model_version=None,
            )
        assert mismatch.value.status_code == 409
        other_user_id, other_token = register(client, "other-usage-owner@example.com")
        with pytest.raises(HTTPException) as isolated:
            reserve_inference(
                db=db,
                user_id=uuid.UUID(other_user_id),
                conversation_id=None,
                request_id=request_id,
                request_hash=fingerprint,
                input_tokens=10,
                reserved_tokens=20,
                model_version=None,
            )
        assert isolated.value.status_code == 404

        failed_request_id = uuid.uuid4()
        failed, created = reserve_inference(
            db=db,
            user_id=uuid.UUID(user_id),
            conversation_id=conversation_id,
            request_id=failed_request_id,
            request_hash="f" * 64,
            input_tokens=1,
            reserved_tokens=1,
            model_version=None,
        )
        assert created is True
        finish_inference(db, failed, "failed")

        next_usage, created = reserve_inference(
            db=db,
            user_id=uuid.UUID(user_id),
            conversation_id=conversation_id,
            request_id=uuid.uuid4(),
            request_hash="e" * 64,
            input_tokens=1,
            reserved_tokens=1,
            model_version=None,
        )
        assert created is True
        assert next_usage.status == "running"
        with pytest.raises(HTTPException) as exceeded:
            reserve_inference(
                db=db,
                user_id=uuid.UUID(user_id),
                conversation_id=conversation_id,
                request_id=uuid.uuid4(),
                request_hash="c" * 64,
                input_tokens=1,
                reserved_tokens=1,
                model_version=None,
            )
        assert exceeded.value.status_code == 429
        assert exceeded.value.detail["metric"] == "requests"

    usage = client.get("/users/me/usage", headers=headers)
    assert usage.status_code == 200
    assert usage.json()["successful_requests"] == 1
    assert usage.json()["input_tokens"] == 10
    assert usage.json()["output_tokens"] == 20
    assert usage.json()["total_tokens"] == 30
    quota = client.get("/users/me/quota", headers=headers)
    assert quota.status_code == 200
    assert quota.json()["requests_in_use"] == 2
    other_usage = client.get(
        "/users/me/usage",
        headers=auth(other_token),
    )
    assert other_usage.status_code == 200
    assert other_usage.json()["successful_requests"] == 0
    assert other_usage.json()["records"] == []
    assert client.delete(
        f"/conversations/{conversation_id}",
        headers=headers,
    ).status_code == 204

    with session_factory() as db:
        assert db.query(InferenceUsage).filter(
            InferenceUsage.request_id == request_id
        ).count() == 1
        assert db.query(InferenceUsage).count() == 3
        assert db.query(InferenceUsage).filter(
            InferenceUsage.conversation_id.is_not(None)
        ).count() == 0


def test_concurrent_reservations_do_not_exceed_request_quota(profile_usage_client):
    _, session_factory = profile_usage_client
    user_id = uuid.uuid4()
    with session_factory() as db:
        db.add(User(id=user_id, email="concurrent-quota@example.com", password_hash="x"))
        db.add(UserQuotaPolicy(user_id=user_id, max_requests=1))
        db.commit()

    start = Barrier(2)

    def reserve(request_id: uuid.UUID):
        with session_factory() as db:
            start.wait()
            try:
                usage, created = reserve_inference(
                    db=db,
                    user_id=user_id,
                    conversation_id=None,
                    request_id=request_id,
                    request_hash=request_id.hex,
                    input_tokens=1,
                    reserved_tokens=8,
                    model_version=None,
                )
                return usage, created, None
            except HTTPException as exc:
                return None, False, exc.status_code

    request_ids = (uuid.uuid4(), uuid.uuid4())
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, request_ids))

    assert sorted(result[2] or 201 for result in results) == [201, 429]
    accepted = next(result[0] for result in results if result[0] is not None)
    with session_factory() as db:
        assert db.query(InferenceUsage).filter_by(user_id=user_id).count() == 1
        reserved = db.query(InferenceUsage).filter_by(
            request_id=accepted.request_id
        ).one()
        complete_inference(db, reserved, input_tokens=1, output_tokens=2)
        db.commit()
        replay, created = reserve_inference(
            db=db,
            user_id=user_id,
            conversation_id=None,
            request_id=accepted.request_id,
            request_hash=accepted.request_fingerprint,
            input_tokens=1,
            reserved_tokens=8,
            model_version=None,
        )
        assert created is False
        assert replay.id == accepted.id
        assert db.query(InferenceUsage).filter_by(user_id=user_id).count() == 1


def test_profile_database_failure_is_not_reported_as_success(profile_usage_client):
    client, session_factory = profile_usage_client
    _, token = register(client, "profile-error@example.com")

    def fail_commit(_session):
        raise OperationalError("commit", {}, Exception("unavailable"))

    event.listen(session_factory.class_, "before_commit", fail_commit)
    try:
        response = client.patch(
            "/users/me",
            headers=auth(token),
            json={"email": "changed@example.com"},
        )
    finally:
        event.remove(session_factory.class_, "before_commit", fail_commit)

    assert response.status_code == 503
    assert client.get("/users/me", headers=auth(token)).json()["email"] == (
        "profile-error@example.com"
    )


def test_expired_quota_window_fails_closed(profile_usage_client):
    client, session_factory = profile_usage_client
    user_id, _ = register(client, "expired-quota@example.com")
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        db.add(
            UserQuotaPolicy(
                user_id=uuid.UUID(user_id),
                max_requests=10,
                window_started_at=now - timedelta(days=2),
                window_ends_at=now - timedelta(days=1),
            )
        )
        db.commit()
        with pytest.raises(HTTPException) as expired:
            reserve_inference(
                db=db,
                user_id=uuid.UUID(user_id),
                conversation_id=None,
                request_id=uuid.uuid4(),
                request_hash="b" * 64,
                input_tokens=1,
                reserved_tokens=1,
                model_version=None,
            )
    assert expired.value.status_code == 503
    assert expired.value.detail["code"] == "quota_policy_inactive"
