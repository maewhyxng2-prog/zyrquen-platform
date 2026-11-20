import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from apps.api.database import Base, get_db
from apps.api.main import app
from apps.core.runtime import runtime
from apps.core.model_loader import (
    NativeModelLoader,
)
from apps.core.inference import (
    NativeInferenceEngine,
)
from apps.api.test_inference_api import (
    _make_tiny_model_dir,
    _init_loader,
)
from apps.core.production_client import (
    ProductionClient,
    ProductionError,
)
import uuid
from pathlib import Path
from apps.api.usage_models import UserQuotaPolicy

@pytest.fixture
def pclient(tmp_path, monkeypatch):
    tmp = tmp_path / "tiny-prod"
    mdir = _make_tiny_model_dir(tmp)
    loader = NativeModelLoader(
        model_path=str(mdir)
    )
    _init_loader(loader)
    loader.tokenizer.eos_token_id = None
    old_loader = runtime.loader
    old_engine = runtime.engine
    old_init = runtime._initialized
    runtime.loader = loader
    runtime.engine = NativeInferenceEngine(
        loader
    )
    runtime._initialized = True

    database_engine = create_engine(
        f"sqlite:///{tmp_path / 'production-client.db'}",
        connect_args={"check_same_thread": False},
    )
    @event.listens_for(database_engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(database_engine)
    testing_session = sessionmaker(
        bind=database_engine,
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

    monkeypatch.setenv("JWT_SECRET_KEY", "production-client-test-secret")
    app.dependency_overrides[get_db] = override_db
    test_client = TestClient(app, client=("127.0.0.1", 12345))
    registered = test_client.post(
        "/auth/register",
        json={"email": "production-client@example.com", "password": "StrongPass123456"},
    )
    assert registered.status_code == 200
    login = test_client.post(
        "/auth/login",
        json={"email": "production-client@example.com", "password": "StrongPass123456"},
    )
    assert login.status_code == 200
    with testing_session() as db:
        db.add(
            UserQuotaPolicy(
                user_id=uuid.UUID(registered.json()["id"]),
                max_requests=10,
                max_input_tokens=10000,
                max_output_tokens=10000,
                max_total_tokens=20000,
            )
        )
        db.commit()
    test_client.headers.update(
        {"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    c = ProductionClient(test_client)
    yield c
    test_client.close()
    app.dependency_overrides.clear()
    runtime.loader = old_loader
    runtime.engine = old_engine
    runtime._initialized = old_init
    database_engine.dispose()

def test_01_health(pclient):
    assert pclient.health() is True

def test_02_infer(pclient):
    out = pclient.infer(
        "hello world",
        max_tokens=8,
        temperature=0.0,
    )
    assert isinstance(out, str)
    assert out.strip() != ""

def test_03_stream(pclient):
    toks = list(
        pclient.infer_stream(
            "hello world",
            max_tokens=8,
            temperature=0.7,
            top_k=5,
            top_p=0.9,
        )
    )
    assert len(toks) >= 1
    assert len(toks) <= 8
    assert "".join(toks).strip() != ""

def test_04_validation_error(pclient):
    with pytest.raises(ProductionError):
        pclient.infer(
            "hello world",
            max_tokens=8,
            temperature=0.7,
            top_p=1.5,
        )
