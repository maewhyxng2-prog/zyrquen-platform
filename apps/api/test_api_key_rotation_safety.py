import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from apps.api.api_access import get_inference_user
from apps.api.api_access_models import ApiKey
from apps.api.database import Base, get_db
from apps.api.main import app


@pytest.fixture
def rotation_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api-key-rotation-safety.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setenv("JWT_SECRET_KEY", "api-key-rotation-test-secret")
    monkeypatch.setenv("ZYRQUEN_TRUSTED_PROXY_IPS", "")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        yield client, session_factory
    app.dependency_overrides.clear()
    engine.dispose()


def _register_and_authenticate(client: TestClient) -> str:
    email = f"rotation-{uuid.uuid4().hex}@example.test"
    password = "StrongPass123456"
    registered = client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert registered.status_code == 200
    login = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    return login.json()["access_token"]


def test_listing_due_key_is_read_only_and_explicit_rotation_delivers_new_secret(
    rotation_client,
):
    client, session_factory = rotation_client
    token = _register_and_authenticate(client)
    headers = {"Authorization": f"Bearer {token}"}
    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    created = client.post(
        "/users/me/api-keys",
        headers=headers,
        json={
            "name": "rotation-safety",
            "expires_at": expires_at,
            "auto_rotate_enabled": True,
            "auto_rotate_interval_days": 1,
        },
    )
    assert created.status_code == 201
    created_body = created.json()
    original_secret = created_body["key"]
    key_id = created_body["id"]
    original_prefix = created_body["key_prefix"]

    with session_factory() as db:
        key = db.query(ApiKey).filter(ApiKey.id == uuid.UUID(key_id)).one()
        key.next_rotation_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    listed = client.get("/users/me/api-keys", headers=headers)
    assert listed.status_code == 200
    metadata = next(item for item in listed.json() if item["id"] == key_id)
    assert metadata["key_prefix"] == original_prefix
    assert metadata["rotation_count"] == 0
    assert "key" not in metadata

    with session_factory() as db:
        old_user = get_inference_user(
            request=Request({"type": "http", "headers": []}),
            token=original_secret,
            db=db,
        )
        assert old_user is not None

    rotated = client.post(
        f"/users/me/api-keys/{key_id}/rotate",
        headers=headers,
    )
    assert rotated.status_code == 200
    rotated_body = rotated.json()
    replacement_secret = rotated_body["key"]
    assert replacement_secret != original_secret
    assert rotated_body["rotation_count"] == 1
    assert rotated_body["last_rotated_at"] is not None

    with session_factory() as db:
        with pytest.raises(Exception):
            get_inference_user(
                request=Request({"type": "http", "headers": []}),
                token=original_secret,
                db=db,
            )
        replacement_user = get_inference_user(
            request=Request({"type": "http", "headers": []}),
            token=replacement_secret,
            db=db,
        )
        assert replacement_user is not None

    listed_again = client.get("/users/me/api-keys", headers=headers)
    assert listed_again.status_code == 200
    final_metadata = next(item for item in listed_again.json() if item["id"] == key_id)
    assert final_metadata["rotation_count"] == 1
    assert "key" not in final_metadata
