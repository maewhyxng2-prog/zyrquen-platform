"""Phase 10.4 — FastAPI Native Runtime Integration Tests.

Covers:
- API fail-closed behavior for not_configured and degraded states (503)
- Exact ZyrquenTokenizer token counting & cfg.max_seq_len context window 422
- Usage and Quota integration with real input_tokens, output_tokens, and model_version
"""
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from apps.api.database import Base, get_db
from apps.api.main import app
from apps.api.usage_models import InferenceUsage, UserQuotaPolicy
from apps.core.inference import NativeInferenceEngine
from apps.core.model_loader import NativeModelLoader
from apps.core.runtime import runtime
from apps.core.test_inference import _init_loader, _make_tiny_model_dir


@pytest.fixture()
def api_db(tmp_path, monkeypatch):
    database_engine = create_engine(
        f"sqlite:///{tmp_path / 'native-runtime-api.db'}",
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

    monkeypatch.setenv("JWT_SECRET_KEY", "native-runtime-api-test-secret")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        reg = client.post(
            "/auth/register",
            json={"email": "native-runtime@example.com", "password": "StrongPass123456"},
        )
        assert reg.status_code == 200
        login = client.post(
            "/auth/login",
            json={"email": "native-runtime@example.com", "password": "StrongPass123456"},
        )
        assert login.status_code == 200
        user_id = UUID(reg.json()["id"])
        with testing_session() as db:
            db.add(
                UserQuotaPolicy(
                    user_id=user_id,
                    max_requests=20,
                    max_input_tokens=10000,
                    max_output_tokens=10000,
                    max_total_tokens=20000,
                )
            )
            db.commit()
        client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
        yield client, testing_session, user_id
    app.dependency_overrides.clear()
    database_engine.dispose()


def _swap_runtime(loader: NativeModelLoader):
    runtime.loader = loader
    runtime.engine = NativeInferenceEngine(loader)
    runtime._initialized = loader.is_ready()


def test_api_fail_closed_not_configured_and_degraded(api_db, tmp_path):
    client, *_ = api_db
    old_loader = runtime.loader
    old_engine = runtime.engine
    old_init = runtime._initialized
    try:
        unconfigured = NativeModelLoader(registry_root=tmp_path / "missing-reg")
        _swap_runtime(unconfigured)
        health_nc = client.get("/v1/native-ai/health")
        assert health_nc.status_code == 200
        assert health_nc.json()["runtime_status"] == "not_configured"
        assert health_nc.json()["inference_available"] is False

        r_nc = client.post(
            "/v1/native-ai/infer",
            json={"prompt": "hello", "request_id": str(uuid4())},
        )
        assert r_nc.status_code == 503
        assert r_nc.json()["detail"]["status"] == "not_configured"

        bad_dir = tmp_path / "hf-invalid"
        bad_dir.mkdir()
        (bad_dir / "config.json").write_text('{"model_type": "gpt2"}', encoding="utf-8")
        degraded = NativeModelLoader(model_path=bad_dir)
        runtime.loader = degraded
        runtime.engine = NativeInferenceEngine(degraded)
        runtime._initialized = False
        assert runtime.initialize() is False

        health_deg = client.get("/v1/native-ai/health")
        assert health_deg.status_code == 200
        assert health_deg.json()["runtime_status"] == "degraded"

        r_deg = client.post(
            "/v1/native-ai/infer",
            json={"prompt": "hello", "request_id": str(uuid4())},
        )
        assert r_deg.status_code == 503
        assert r_deg.json()["detail"]["status"] == "degraded"
    finally:
        runtime.loader = old_loader
        runtime.engine = old_engine
        runtime._initialized = old_init


def test_api_enforces_max_seq_len_and_records_real_usage_and_version(api_db, tmp_path):
    client, session_factory, user_id = api_db
    old_loader = runtime.loader
    old_engine = runtime.engine
    old_init = runtime._initialized
    try:
        reg_root = _make_tiny_model_dir(tmp_path / "native-api", max_seq_len=16)
        loader = NativeModelLoader(registry_root=reg_root)
        _init_loader(loader)
        _swap_runtime(loader)

        tok = loader.tokenizer
        exact_prompt = ""
        for ch in "abcdefghijklmnopqrstuvwxyz":
            cand = exact_prompt + ch
            if len(tok.encode(cand)) <= 16:
                exact_prompt = cand
            if len(tok.encode(exact_prompt)) == 16:
                break
        assert len(tok.encode(exact_prompt)) == 16

        overflow_res = client.post(
            "/v1/native-ai/infer",
            json={
                "prompt": exact_prompt + "!",
                "request_id": str(uuid4()),
                "max_tokens": 4,
            },
        )
        assert overflow_res.status_code == 422

        req_id = str(uuid4())
        ok_res = client.post(
            "/v1/native-ai/infer",
            json={
                "prompt": exact_prompt,
                "request_id": req_id,
                "max_tokens": 4,
                "temperature": 0.0,
            },
        )
        assert ok_res.status_code == 200
        body = ok_res.json()
        assert body["provider"] == "ZYRQUEN_NATIVE_CORE"
        assert body["model_version"] == "ZYRQUEN-Native-0.1.0"

        with session_factory() as db:
            row = (
                db.query(InferenceUsage)
                .filter(InferenceUsage.request_id == UUID(req_id))
                .one()
            )
            assert row.status == "completed"
            assert row.model_version == "ZYRQUEN-Native-0.1.0"
            assert row.input_tokens == 16
            assert 1 <= row.output_tokens <= 4

        usage_res = client.get("/users/me/usage")
        assert usage_res.status_code == 200
        assert usage_res.json()["successful_requests"] == 1
        assert usage_res.json()["input_tokens"] == 16
        assert usage_res.json()["records"][0]["model_version"] == "ZYRQUEN-Native-0.1.0"

        quota_res = client.get("/users/me/quota")
        assert quota_res.status_code == 200
        assert quota_res.json()["requests_in_use"] == 1
        assert quota_res.json()["input_tokens"] == 16
    finally:
        runtime.loader = old_loader
        runtime.engine = old_engine
        runtime._initialized = old_init


def test_api_readiness_fail_closed_with_registry_without_active_version(api_db, tmp_path, monkeypatch):
    import json

    client, *_ = api_db
    old_loader = runtime.loader
    old_engine = runtime.engine
    old_init = runtime._initialized
    try:
        reg_root = tmp_path / "model-registry"
        reg_root.mkdir()
        (reg_root / "registry.json").write_text(
            json.dumps(
                {
                    "schema": "zyrquen.model-registry.v1",
                    "versions": {},
                    "active": None,
                    "history": [],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("ZYRQUEN_MODEL_REGISTRY_ROOT", str(reg_root))
        monkeypatch.delenv("ZYRQUEN_MODEL_PATH", raising=False)
        monkeypatch.delenv("ZYRQUEN_MODEL_VERSION", raising=False)

        loader = NativeModelLoader()
        runtime.loader = loader
        runtime.engine = NativeInferenceEngine(loader)
        runtime._initialized = False
        assert runtime.initialize() is False

        livez = client.get("/livez")
        assert livez.status_code == 200
        assert livez.json()["status"] == "healthy"

        readyz = client.get("/readyz")
        assert readyz.status_code == 503
        assert readyz.json()["status"] != "healthy"
        assert readyz.json()["native_ai"]["runtime_status"] == "not_configured"
        assert readyz.json()["native_ai"]["inference_available"] is False

        health = client.get("/health")
        assert health.status_code == 503
        assert health.json()["native_ai"]["runtime_status"] == "not_configured"
    finally:
        runtime.loader = old_loader
        runtime.engine = old_engine
        runtime._initialized = old_init
