import json
import uuid
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from apps.api.database import Base, get_db
from apps.api.main import app
from apps.api.models import ConversationMessage, User
from apps.api.test_inference_api import _init_loader, _make_tiny_model_dir
from apps.core.model_loader import NativeModelLoader
from apps.core.runtime import runtime
from apps.api.usage_models import InferenceUsage, UserQuotaPolicy


@pytest.fixture
def conversation_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'conversation-tests.db'}",
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

    monkeypatch.setenv("JWT_SECRET_KEY", "conversation-tests-only-secret")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def native_stream_runtime(tmp_path):
    loader = NativeModelLoader(
        model_path=str(_make_tiny_model_dir(tmp_path / "conversation-native-model"))
    )
    _init_loader(loader)
    loader.tokenizer.eos_token_id = None
    old_loader = runtime.loader
    old_initialized = runtime._initialized
    runtime.loader = loader
    runtime._initialized = True
    yield loader
    runtime.loader = old_loader
    runtime._initialized = old_initialized


def register(client: TestClient, email: str) -> tuple[str, str]:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "StrongPass123456"},
    )
    assert response.status_code == 200
    return response.json()["id"], client.post(
        "/auth/login",
        json={"email": email, "password": "StrongPass123456"},
    ).json()["access_token"]


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_conversation_crud_and_ordered_message_persistence(conversation_client):
    client, session_factory = conversation_client
    _, token = register(client, "conversation-owner@example.com")
    auth = headers(token)

    created = client.post("/conversations", headers=auth, json={"title": "First"})
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    assert created.json()["message_count"] == 0

    message_ids = [str(uuid.uuid4())]
    for message_id, role, content in (
        (message_ids[0], "user", "question"),
    ):
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            headers=auth,
            json={"id": message_id, "role": role, "content": content},
        )
        assert response.status_code == 201

    detail = client.get(f"/conversations/{conversation_id}", headers=auth)
    assert detail.status_code == 200
    assert [message["id"] for message in detail.json()["messages"]] == message_ids
    assert detail.json()["message_count"] == 1
    assert detail.json()["messages"][0]["content"] == "question"

    renamed = client.patch(
        f"/conversations/{conversation_id}",
        headers=auth,
        json={"title": "Renamed"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Renamed"

    second = client.post(
        "/conversations",
        headers=auth,
        json={"title": "Second"},
    )
    assert second.status_code == 201
    latest_message = client.post(
        f"/conversations/{conversation_id}/messages",
        headers=auth,
        json={
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": "follow-up",
        },
    )
    assert latest_message.status_code == 201

    listing = client.get("/conversations", headers=auth)
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [
        conversation_id,
        second.json()["id"],
    ]
    assert listing.json()[0]["message_count"] == 2

    assert client.delete(f"/conversations/{conversation_id}", headers=auth).status_code == 204
    with session_factory() as db:
        assert (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == uuid.UUID(conversation_id))
            .count()
            == 0
        )


def test_all_conversation_routes_require_authentication(conversation_client):
    client, _ = conversation_client
    conversation_id = str(uuid.uuid4())
    assert client.get("/conversations").status_code == 401
    assert client.post("/conversations", json={"title": "private"}).status_code == 401
    assert client.get(f"/conversations/{conversation_id}").status_code == 401
    assert (
        client.patch(
            f"/conversations/{conversation_id}",
            json={"title": "changed"},
        ).status_code
        == 401
    )
    assert client.delete(f"/conversations/{conversation_id}").status_code == 401
    assert (
        client.post(
            f"/conversations/{conversation_id}/messages",
            json={
                "id": str(uuid.uuid4()),
                "role": "user",
                "content": "text",
            },
        ).status_code
        == 401
    )


def test_cross_user_isolation_and_not_found_responses(conversation_client):
    client, _ = conversation_client
    _, token_a = register(client, "owner-a@example.com")
    _, token_b = register(client, "owner-b@example.com")
    created = client.post(
        "/conversations",
        headers=headers(token_a),
        json={"title": "A private conversation"},
    )
    conversation_id = created.json()["id"]

    assert client.get("/conversations", headers=headers(token_b)).json() == []
    assert client.get(
        f"/conversations/{conversation_id}", headers=headers(token_b)
    ).status_code == 404
    assert client.patch(
        f"/conversations/{conversation_id}",
        headers=headers(token_b),
        json={"title": "stolen"},
    ).status_code == 404
    assert client.delete(
        f"/conversations/{conversation_id}", headers=headers(token_b)
    ).status_code == 404
    assert client.post(
        f"/conversations/{conversation_id}/messages",
        headers=headers(token_b),
        json={
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": "not allowed",
        },
    ).status_code == 404
    assert client.get(
        f"/conversations/{conversation_id}", headers=headers(token_a)
    ).json()["title"] == "A private conversation"


def test_duplicate_message_ids_are_idempotent_and_conflicts_are_rejected(
    conversation_client,
):
    client, _ = conversation_client
    _, token = register(client, "message-owner@example.com")
    auth = headers(token)
    conversation_id = client.post(
        "/conversations",
        headers=auth,
        json={"title": "Messages"},
    ).json()["id"]
    message_id = str(uuid.uuid4())
    payload = {"id": message_id, "role": "user", "content": "once"}

    assert client.post(
        f"/conversations/{conversation_id}/messages",
        headers=auth,
        json=payload,
    ).status_code == 201
    assert client.post(
        f"/conversations/{conversation_id}/messages",
        headers=auth,
        json=payload,
    ).status_code == 201
    assert client.post(
        f"/conversations/{conversation_id}/messages",
        headers=auth,
        json={**payload, "content": "different"},
    ).status_code == 409
    detail = client.get(f"/conversations/{conversation_id}", headers=auth).json()
    assert detail["message_count"] == 1
    assert [message["content"] for message in detail["messages"]] == ["once"]


def test_client_cannot_create_assistant_message(conversation_client):
    client, _ = conversation_client
    _, token = register(client, "user-only@example.com")
    auth = headers(token)
    conversation_id = client.post(
        "/conversations",
        headers=auth,
        json={"title": "No direct assistant"},
    ).json()["id"]

    response = client.post(
        f"/conversations/{conversation_id}/messages",
        headers=auth,
        json={
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": "client-forged",
        },
    )

    assert response.status_code == 422


def test_completed_native_stream_persists_assistant_once(
    conversation_client,
    native_stream_runtime,
):
    client, session_factory = conversation_client
    _, token = register(client, "native-owner@example.com")
    auth = headers(token)
    conversation_id = client.post(
        "/conversations",
        headers=auth,
        json={"title": "Native stream"},
    ).json()["id"]
    with session_factory() as db:
        from apps.api.models import Conversation
        conversation = db.get(Conversation, uuid.UUID(conversation_id))
        db.add(
            UserQuotaPolicy(
                user_id=conversation.user_id,
                max_requests=10,
                max_input_tokens=1000,
                max_output_tokens=1000,
                max_total_tokens=2000,
            )
        )
        db.commit()

    request_id = str(uuid.uuid4())
    response = client.post(
        "/v1/native-ai/infer/stream",
        headers=auth,
        json={
            "prompt": "hello",
            "conversation_id": conversation_id,
            "request_id": request_id,
            "max_tokens": 8,
            "temperature": 0.0,
        },
    )
    assert response.status_code == 200
    assert "[DONE]" in response.text

    response = client.post(
        "/v1/native-ai/infer/stream",
        headers=auth,
        json={
            "prompt": "hello",
            "conversation_id": conversation_id,
            "request_id": request_id,
            "max_tokens": 8,
            "temperature": 0.0,
        },
    )
    assert response.status_code == 200
    assert "[DONE]" in response.text

    with session_factory() as db:
        messages = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == uuid.UUID(conversation_id))
            .all()
        )
        assert len(messages) == 1
        assert messages[0].id == uuid.UUID(request_id)
        assert messages[0].role == "assistant"
        assert messages[0].content.strip()
        usage = db.query(InferenceUsage).filter(
            InferenceUsage.request_id == uuid.UUID(request_id)
        ).one()
        assert usage.status == "completed"
        assert usage.input_tokens > 0
        assert usage.output_tokens > 0


@pytest.mark.parametrize(
    "failure_mode",
    [
        "missing_final",
        "runtime_error",
        "cancelled",
    ],
)
def test_incomplete_or_failed_native_stream_does_not_persist(
    conversation_client,
    native_stream_runtime,
    failure_mode,
):
    client, session_factory = conversation_client
    _, token = register(client, f"{failure_mode}@example.com")
    auth = headers(token)
    conversation_id = client.post(
        "/conversations",
        headers=auth,
        json={"title": "Failure"},
    ).json()["id"]
    with session_factory() as db:
        from apps.api.models import Conversation
        conversation = db.get(Conversation, uuid.UUID(conversation_id))
        db.add(
            UserQuotaPolicy(
                user_id=conversation.user_id,
                max_requests=10,
                max_input_tokens=1000,
                max_output_tokens=1000,
                max_total_tokens=2000,
            )
        )
        db.commit()

    calls = 0

    def interrupt_native_model(_module, _inputs, _output):
        nonlocal calls
        calls += 1
        if failure_mode in {"missing_final", "cancelled"} and calls < 2:
            return
        if failure_mode == "cancelled":
            raise asyncio.CancelledError()
        raise RuntimeError("Native model forward failed")

    hook = native_stream_runtime.model.register_forward_hook(
        interrupt_native_model
    )
    response = client.post(
        "/v1/native-ai/infer/stream",
        headers=auth,
        json={
            "prompt": "hello",
            "conversation_id": conversation_id,
            "request_id": str(uuid.uuid4()),
            "max_tokens": 8,
            "temperature": 0.0,
        },
    )
    hook.remove()

    assert response.status_code == 200
    assert "[DONE]" not in response.text
    if failure_mode != "cancelled":
        assert "error" in response.text
    with session_factory() as db:
        assert db.query(ConversationMessage).count() == 0
        failed_usage = db.query(InferenceUsage).one()
        assert failed_usage.status in {"failed", "cancelled"}
        assert failed_usage.output_tokens == 0


def test_native_stream_cross_user_isolation(conversation_client):
    client, _ = conversation_client
    _, token_a = register(client, "stream-owner@example.com")
    _, token_b = register(client, "stream-other@example.com")
    conversation_id = client.post(
        "/conversations",
        headers=headers(token_a),
        json={"title": "Private"},
    ).json()["id"]

    response = client.post(
        "/v1/native-ai/infer/stream",
        headers=headers(token_b),
        json={
            "prompt": "hello",
            "conversation_id": conversation_id,
            "request_id": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 404


def test_native_stream_commit_failure_rolls_back(
    conversation_client,
    native_stream_runtime,
):
    client, session_factory = conversation_client
    _, token = register(client, "rollback-owner@example.com")
    auth = headers(token)
    conversation_id = client.post(
        "/conversations",
        headers=auth,
        json={"title": "Rollback"},
    ).json()["id"]
    with session_factory() as db:
        from apps.api.models import Conversation
        conversation = db.get(Conversation, uuid.UUID(conversation_id))
        db.add(
            UserQuotaPolicy(
                user_id=conversation.user_id,
                max_requests=10,
                max_input_tokens=1000,
                max_output_tokens=1000,
                max_total_tokens=2000,
            )
        )
        db.commit()

    def fail_commit(_session, _flush_context, _instances):
        pending_messages = [
            obj for obj in _session.new if isinstance(obj, ConversationMessage)
        ]
        if pending_messages:
            raise OperationalError("commit", {}, Exception("unavailable"))

    event.listen(session_factory.class_, "before_flush", fail_commit)
    try:
        response = client.post(
            "/v1/native-ai/infer/stream",
            headers=auth,
            json={
                "prompt": "hello",
                "conversation_id": conversation_id,
                "request_id": str(uuid.uuid4()),
                "max_tokens": 8,
                "temperature": 0.0,
            },
        )
    finally:
        event.remove(session_factory.class_, "before_flush", fail_commit)

    assert "[DONE]" not in response.text
    events = [
        json.loads(frame.removeprefix("data: "))
        for frame in response.text.strip().split("\n\n")
        if frame.startswith("data: ")
    ]
    assert any(
        event_data.get("error") == "ระบบจัดเก็บบทสนทนาไม่พร้อมใช้งานชั่วคราว"
        for event_data in events
    )
    with session_factory() as db:
        assert db.query(ConversationMessage).count() == 0
        usage = db.query(InferenceUsage).one()
        assert usage.status == "failed"


def test_database_commit_failure_is_not_reported_as_success(conversation_client):
    client, session_factory = conversation_client
    _, token = register(client, "database-error@example.com")

    def fail_commit(_session):
        raise OperationalError("commit", {}, Exception("unavailable"))

    event.listen(session_factory.class_, "before_commit", fail_commit, once=True)
    response = client.post(
        "/conversations",
        headers=headers(token),
        json={"title": "Must not persist"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Conversation storage is temporarily unavailable"
    with session_factory() as db:
        assert db.query(User).filter(User.email == "database-error@example.com").count() == 1
