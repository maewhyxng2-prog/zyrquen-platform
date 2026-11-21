"""PostgreSQL integration coverage. This module never runs unless explicitly gated."""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from apps.api.database_safety import (
    validate_database_target,
    verify_test_database_connection,
)


pytestmark = pytest.mark.skipif(
    os.getenv("ZYRQUEN_PG_INTEGRATION") != "1",
    reason="PostgreSQL integration requires an explicitly gated Test database",
)


def _target():
    if os.getenv("PGHOSTADDR") or os.getenv("PGSERVICE"):
        pytest.fail("PG routing override is not allowed")
    return validate_database_target(
        os.getenv("DATABASE_URL"),
        os.environ,
        for_migration=False,
    )


def _engine():
    target = _target()
    assert target.environment == "test"
    assert target.url.get_backend_name() == "postgresql"
    return create_engine(target.url, pool_pre_ping=True, hide_parameters=True)


@pytest.fixture(scope="module")
def pg_engine():
    engine = _engine()
    with engine.connect() as connection:
        verify_test_database_connection(connection, _target())
        connection.exec_driver_sql("SELECT 1")

    config = Config("apps/api/alembic.ini")
    config.set_main_option("script_location", "apps/api/migrations")
    command.upgrade(config, "head")
    yield engine
    command.upgrade(config, "head")
    engine.dispose()


@pytest.fixture
def Session(pg_engine):
    return sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)


def test_migration_cycle_on_empty_test_database(pg_engine):
    config = Config("apps/api/alembic.ini")
    config.set_main_option("script_location", "apps/api/migrations")
    command.downgrade(config, "base")

    inspector_tables = __import__("sqlalchemy").inspect(pg_engine).get_table_names()
    assert "users" not in inspector_tables
    assert "training_runs" not in inspector_tables

    command.upgrade(config, "head")
    inspector = __import__("sqlalchemy").inspect(pg_engine)
    expected = {
        "users",
        "training_runs",
        "evaluation_runs",
        "revoked_tokens",
        "conversations",
        "conversation_messages",
        "user_quota_policies",
        "inference_usage",
        "api_keys",
        "audit_logs",
        "login_rate_limits",
    }
    assert expected.issubset(set(inspector.get_table_names()))

    command.downgrade(config, "base")
    assert not expected.intersection(
        set(__import__("sqlalchemy").inspect(pg_engine).get_table_names())
    )
    command.upgrade(config, "head")
    assert expected.issubset(
        set(__import__("sqlalchemy").inspect(pg_engine).get_table_names())
    )


def test_quota_concurrency_and_idempotency(pg_engine, Session):
    from apps.api.models import User
    from apps.api.usage import reserve_inference
    from apps.api.usage_models import UserQuotaPolicy

    with Session() as db:
        user = User(
            id=uuid.uuid4(),
            email=f"quota-{uuid.uuid4()}@example.test",
            password_hash="test",
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(
            UserQuotaPolicy(
                user_id=user.id,
                max_requests=3,
                max_input_tokens=None,
                max_output_tokens=None,
                max_total_tokens=None,
                window_started_at=None,
                window_ends_at=None,
            )
        )
        db.commit()
        user_id = user.id

    barrier = threading.Barrier(5)

    def reserve_one(index):
        request_id = uuid.uuid4()
        with Session() as db:
            barrier.wait(timeout=10)
            try:
                reserve_inference(
                    db=db,
                    user_id=user_id,
                    conversation_id=None,
                    request_id=request_id,
                    request_hash=f"{index:064d}",
                    input_tokens=10,
                    reserved_tokens=20,
                    model_version=None,
                    api_key_id=None,
                )
                return "accepted"
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(reserve_one, range(5)))
    assert results.count("accepted") == 3
    assert results.count(429) == 2

    with Session() as db:
        replay_user = User(
            id=uuid.uuid4(),
            email=f"replay-{uuid.uuid4()}@example.test",
            password_hash="test",
            is_active=True,
        )
        db.add(replay_user)
        db.flush()
        db.add(
            UserQuotaPolicy(
                user_id=replay_user.id,
                max_requests=10,
                max_input_tokens=None,
                max_output_tokens=None,
                max_total_tokens=None,
                window_started_at=None,
                window_ends_at=None,
            )
        )
        db.commit()
        replay_user_id = replay_user.id

    repeated_id = uuid.uuid4()
    fingerprint = "0" * 64

    def repeated():
        with Session() as db:
            try:
                return reserve_inference(
                    db=db,
                    user_id=replay_user_id,
                    conversation_id=None,
                    request_id=repeated_id,
                    request_hash=fingerprint,
                    input_tokens=10,
                    reserved_tokens=20,
                    model_version=None,
                    api_key_id=None,
                )[1]
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        repeated_results = list(pool.map(lambda _: repeated(), range(2)))
    assert repeated_results.count(True) == 1
    assert repeated_results.count(409) == 1

    replay_id = uuid.uuid4()
    replay_fingerprint = "1" * 64
    with Session() as db:
        from apps.api.usage import complete_inference
        usage, created = reserve_inference(
            db=db,
            user_id=replay_user_id,
            conversation_id=None,
            request_id=replay_id,
            request_hash=replay_fingerprint,
            input_tokens=10,
            reserved_tokens=20,
            model_version=None,
            api_key_id=None,
        )
        if created:
            complete_inference(db, usage, input_tokens=10, output_tokens=20)
            db.commit()
    with Session() as db:
        replay_usage, replay_created = reserve_inference(
            db=db,
            user_id=replay_user_id,
            conversation_id=None,
            request_id=replay_id,
            request_hash=replay_fingerprint,
            input_tokens=10,
            reserved_tokens=20,
            model_version=None,
            api_key_id=None,
        )
        assert replay_created is False
        db.rollback()

    from apps.api.usage import complete_inference, finish_inference
    from apps.api.usage_models import InferenceUsage

    rollback_id = uuid.uuid4()
    with Session() as db:
        usage, created = reserve_inference(
            db=db,
            user_id=replay_user_id,
            conversation_id=None,
            request_id=rollback_id,
            request_hash="f" * 64,
            input_tokens=10,
            reserved_tokens=20,
            model_version=None,
            api_key_id=None,
        )
        assert created is True
        complete_inference(db, usage, input_tokens=10, output_tokens=20)
        db.rollback()
    with Session() as db:
        row = db.query(InferenceUsage).filter(
            InferenceUsage.request_id == rollback_id
        ).first()
        assert row is not None
        assert row.status == "running"
        assert row.output_tokens == 0
        assert row.reserved_tokens == 20
        finish_inference(db, row, "failed")
    with Session() as db:
        released = db.query(InferenceUsage).filter(
            InferenceUsage.request_id == rollback_id
        ).first()
        assert released is not None
        assert released.status == "failed"
        assert released.reserved_tokens == 0


def test_http_multi_user_auth_isolation_and_api_keys(pg_engine, Session):
    from apps.api.api_access_models import ApiKey
    from apps.api.api_access import api_key_digest
    from apps.api.main import app
    from apps.api.models import User

    client = TestClient(app, client=("127.0.0.1", 12345))
    suffix = uuid.uuid4().hex
    email_a = f"a-{suffix}@example.test"
    email_b = f"b-{suffix}@example.test"

    register_a = client.post(
        "/auth/register",
        json={"email": email_a, "password": "StrongPassword123!"},
    )
    register_b = client.post(
        "/auth/register",
        json={"email": email_b, "password": "StrongPassword123!"},
    )
    assert register_a.status_code == 200
    assert register_b.status_code == 200

    login_a = client.post(
        "/auth/login",
        json={"email": email_a, "password": "StrongPassword123!"},
    )
    login_b = client.post(
        "/auth/login",
        json={"email": email_b, "password": "StrongPassword123!"},
    )
    assert login_a.status_code == 200
    assert login_b.status_code == 200
    token_a = login_a.json()["access_token"]
    token_b = login_b.json()["access_token"]

    bad_login = client.post(
        "/auth/login",
        json={"email": f"missing-{suffix}@example.test", "password": "wrong"},
    )
    assert bad_login.status_code == 401

    admin_response = client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert admin_response.status_code == 403

    with Session() as db:
        user_a = db.query(User).filter(User.email == email_a).first()
        user_b = db.query(User).filter(User.email == email_b).first()
        assert user_a is not None
        assert user_b is not None
        user_a.role = "admin"
        secret = "zyr_" + uuid.uuid4().hex
        key = ApiKey(
            id=uuid.uuid4(),
            user_id=user_a.id,
            name="integration-key",
            key_prefix="zyr_",
            key_hash=api_key_digest(secret),
            scope="native:inference",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            revoked_at=None,
        )
        db.add(key)
        db.commit()
        key_id = key.id

    admin_response = client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert admin_response.status_code == 200

    conversation_a = client.post(
        "/conversations",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "private-a"},
    )
    assert conversation_a.status_code == 200
    conversation_id = conversation_a.json()["id"]
    cross_read = client.get(
        f"/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert cross_read.status_code in (403, 404)
    cross_delete = client.delete(
        f"/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert cross_delete.status_code in (403, 404)

    usage_a = client.get(
        "/users/me/usage",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    usage_b = client.get(
        "/users/me/usage",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert usage_a.status_code == 200
    assert usage_b.status_code == 200

    logout_a = client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert logout_a.status_code == 200
    revoked_bearer = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert revoked_bearer.status_code == 401

    with Session() as db:
        key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
        assert key is not None
        key.revoked_at = datetime.now(timezone.utc)
        db.commit()

    revoked = client.post(
        "/v1/native-ai/infer",
        headers={"Authorization": "Bearer zyr_" + secret.split("zyr_", 1)[1]},
        json={
            "request_id": str(uuid.uuid4()),
            "prompt": "not executed",
            "max_tokens": 8,
        },
    )
    assert revoked.status_code == 401
