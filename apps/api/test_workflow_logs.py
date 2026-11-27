from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from apps.api.database import Base, get_db
from apps.api.main import app
from apps.api.models import User
from apps.api.routers import workflows as workflows_router


@pytest.fixture
def workflow_logs_client(tmp_path: Path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'workflow-logs-api.db'}",
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

    monkeypatch.setenv("JWT_SECRET_KEY", "workflow-logs-test-secret-key")
    monkeypatch.setenv("ZYRQUEN_WORKFLOW_DB_PATH", str(tmp_path / "workflows.db"))
    workflows_router._ENGINE = None
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    workflows_router._ENGINE = None
    engine.dispose()


def _register_and_login(
    client: TestClient,
    session_factory,
    email: str,
    *,
    role: str = "user",
) -> str:
    reg = client.post(
        "/auth/register",
        json={"email": email, "password": "StrongPassword12345"},
    )
    assert reg.status_code == 200
    if role == "admin":
        with session_factory() as db:
            user = db.query(User).filter(User.email == email).first()
            assert user is not None
            user.role = "admin"
            db.commit()
    login = client.post(
        "/auth/login",
        json={"email": email, "password": "StrongPassword12345"},
    )
    assert login.status_code == 200
    return login.json()["access_token"]


def test_workflow_logs_auth_empty_and_isolation(workflow_logs_client):
    client, session_factory = workflow_logs_client

    # 1. Unauthenticated caller MUST receive 401
    unauth = client.get("/v1/workflows/logs")
    assert unauth.status_code == 401

    admin_token = _register_and_login(client, session_factory, "wf-admin@example.com", role="admin")
    alice_token = _register_and_login(client, session_factory, "wf-alice@example.com", role="user")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    alice_headers = {"Authorization": f"Bearer {alice_token}"}

    # 2. Authenticated caller with ZERO workflow runs/logs MUST receive 200 with empty lists (never 403)
    for active_only in ("true", "false"):
        empty_resp = client.get(f"/v1/workflows/logs?active_only={active_only}", headers=alice_headers)
        assert empty_resp.status_code == 200
        body = empty_resp.json()
        assert body["items"] == []
        assert body["active_runs"] == []

    # 3. Invalid run_id -> 400; nonexistent run_id -> 404
    bad_run = client.get("/v1/workflows/logs?run_id=../escape", headers=alice_headers)
    assert bad_run.status_code == 400

    missing_run = client.get("/v1/workflows/logs?run_id=missing-run-id", headers=alice_headers)
    assert missing_run.status_code == 404

    # 4. Trigger admin-owned and Alice-owned runs
    admin_run = client.post(
        "/v1/workflows/runs",
        headers=admin_headers,
        json={"workflow_key": "training.native_controlled_run", "execute_async": False},
    )
    assert admin_run.status_code == 202
    admin_run_id = admin_run.json()["id"]

    alice_run = client.post(
        "/v1/workflows/runs",
        headers=alice_headers,
        json={"workflow_key": "training.native_controlled_run", "execute_async": False},
    )
    assert alice_run.status_code == 202
    alice_run_id = alice_run.json()["id"]

    # 5. Cross-user run_id query MUST return 403
    cross_run = client.get(
        f"/v1/workflows/logs?run_id={admin_run_id}&active_only=false",
        headers=alice_headers,
    )
    assert cross_run.status_code == 403

    # 6. Alice sees ONLY Alice's runs/logs
    alice_logs = client.get("/v1/workflows/logs?active_only=false", headers=alice_headers)
    assert alice_logs.status_code == 200
    alice_items = alice_logs.json()["items"]
    assert len(alice_items) > 0
    assert all(item["run_id"] == alice_run_id for item in alice_items)

    # 7. Invalid level -> 400; valid level + search filters work accurately
    bad_level = client.get("/v1/workflows/logs?level=TRACE", headers=alice_headers)
    assert bad_level.status_code == 400

    filtered_logs = client.get(
        "/v1/workflows/logs?active_only=false&level=INFO&search=training",
        headers=alice_headers,
    )
    assert filtered_logs.status_code == 200
    filtered_items = filtered_logs.json()["items"]
    assert all(item["level"] == "INFO" and item["run_id"] == alice_run_id for item in filtered_items)
