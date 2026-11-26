"""Regression tests for Phase 6.1 Authentication & Multi-user Readiness Gate."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.database import Base, get_db
from apps.api.evaluation_models import EvaluationRun
from apps.api.main import app
from apps.api.models import User
from apps.api.security import ALGORITHM
from apps.api.training_models import TrainingRun


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth-gate-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-for-auth-gate-only")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        yield client, TestingSession
    app.dependency_overrides.clear()
    engine.dispose()


def _register_and_login(client: TestClient, email: str, password: str = "StrongPass123456"):
    reg = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert reg.status_code == 200
    reg_body = reg.json()
    assert reg_body["email"] == email.strip().lower()
    assert "password_hash" not in reg_body
    assert "password" not in reg_body

    login = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    return reg_body["id"], token


def test_session_me_and_protected_routes_require_real_auth(auth_client):
    client, _ = auth_client

    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/logout").status_code == 401
    assert (
        client.post(
            "/v1/native-ai/infer",
            json={"prompt": "hello", "request_id": str(uuid.uuid4())},
        ).status_code
        == 401
    )

    user_id, token = _register_and_login(client, "alice@example.com")
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    payload = me.json()
    assert payload["id"] == user_id
    assert payload["email"] == "alice@example.com"
    assert payload["is_active"] is True
    assert "password_hash" not in payload
    assert "access_token" not in payload


def test_logout_revokes_token_against_backend(auth_client):
    client, _ = auth_client
    _, token = _register_and_login(client, "bob@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/auth/me", headers=headers).status_code == 200

    logout_res = client.post("/auth/logout", headers=headers)
    assert logout_res.status_code == 200
    assert logout_res.json() == {"authenticated": False, "revoked": True}

    assert client.get("/auth/me", headers=headers).status_code == 401
    assert (
        client.post(
            "/v1/native-ai/infer",
            headers=headers,
            json={"prompt": "test", "request_id": str(uuid.uuid4())},
        ).status_code
        == 401
    )


def test_expired_token_and_inactive_account_are_rejected(auth_client):
    client, session_factory = auth_client
    user_id, _ = _register_and_login(client, "carol@example.com")

    expired_token = jwt.encode(
        {
            "sub": user_id,
            "jti": str(uuid.uuid4()),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        },
        "test-secret-key-for-auth-gate-only",
        algorithm=ALGORITHM,
    )
    assert (
        client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        ).status_code
        == 401
    )

    _, valid_token = _register_and_login(client, "disabled@example.com")
    with session_factory() as db:
        user = db.query(User).filter(User.email == "disabled@example.com").first()
        user.is_active = False
        db.commit()

    assert (
        client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {valid_token}"},
        ).status_code
        == 403
    )


def test_multi_user_isolation_and_backend_authorization(auth_client, monkeypatch):
    client, session_factory = auth_client
    admin_a_id, token_a = _register_and_login(client, "admin-a@example.com")
    _, token_b = _register_and_login(client, "admin-b@example.com")
    _, token_user = _register_and_login(client, "regular@example.com")

    monkeypatch.setenv(
        "ZYRQUEN_TRAINING_ADMIN_EMAILS",
        "admin-a@example.com,admin-b@example.com",
    )

    run_id = uuid.uuid4()
    with session_factory() as db:
        db.add(
            TrainingRun(
                id=run_id,
                owner_id=uuid.UUID(admin_a_id),
                status="completed",
                dataset_version="0.1.0",
                training_config={"max_steps": 5},
                model_config={"n_layers": 1},
            )
        )
        eval_run = EvaluationRun(
            user_id=uuid.UUID(admin_a_id),
            model_version="v1",
            dataset_id="dataset-v1",
            dataset_checksum="abc123",
            status="queued",
        )
        db.add(eval_run)
        db.commit()
        db.refresh(eval_run)
        eval_id = eval_run.id

    assert (
        client.get(
            f"/training/runs/{run_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/training/runs/{run_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/training/runs/{run_id}",
            headers={"Authorization": f"Bearer {token_user}"},
        ).status_code
        == 403
    )

    assert (
        client.get(
            f"/v1/evaluation/runs/{eval_id}",
            headers={"Authorization": f"Bearer {token_user}"},
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/v1/evaluation/runs/{eval_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        ).status_code
        == 200
    )
