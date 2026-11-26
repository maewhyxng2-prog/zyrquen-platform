import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.database import Base, get_db
from apps.api.main import app
from apps.api.models import User
from apps.api.routers.training import get_current_user
from apps.api.training_models import TrainingRun
from apps.core.training_infrastructure.monitoring.training_monitor import (
    TrainingMonitor,
)
from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
    CheckpointManager,
)


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'training-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    user_id = uuid.uuid4()
    with TestingSession() as db:
        db.add(
            User(
                id=user_id,
                email="training-admin@example.com",
                password_hash="unused-in-this-test",
            )
        )
        db.commit()

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    test_user = User(
        id=user_id,
        email="training-admin@example.com",
        password_hash="unused-in-this-test",
    )
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    monkeypatch.setenv(
        "ZYRQUEN_TRAINING_ADMIN_EMAILS", "training-admin@example.com"
    )
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        yield client, TestingSession, test_user
    app.dependency_overrides.clear()
    engine.dispose()


def test_training_routes_require_authentication(api_client, monkeypatch):
    client, _, _ = api_client
    app.dependency_overrides.pop(get_current_user)
    monkeypatch.setenv(
        "ZYRQUEN_TRAINING_ADMIN_EMAILS", "training-admin@example.com"
    )

    response = client.post(
        "/training/runs",
        json={"dataset_version": "0.1.0"},
    )

    assert response.status_code == 401


def test_training_routes_require_configured_admin(api_client, monkeypatch):
    client, _, _ = api_client
    monkeypatch.setenv("ZYRQUEN_TRAINING_ADMIN_EMAILS", "")

    response = client.post(
        "/training/runs",
        json={"dataset_version": "0.1.0"},
    )

    assert response.status_code == 503
    assert "allowlist is not configured" in response.json()["detail"]


def test_non_admin_cannot_start_training(api_client, monkeypatch):
    client, _, _ = api_client
    monkeypatch.setenv(
        "ZYRQUEN_TRAINING_ADMIN_EMAILS", "another-admin@example.com"
    )

    response = client.post(
        "/training/runs",
        json={"dataset_version": "0.1.0"},
    )

    assert response.status_code == 403


def test_missing_training_artifacts_return_503(api_client, tmp_path, monkeypatch):
    client, _, user = api_client

    # The security gate must reject requests without approval before checking artifacts.
    no_approval = client.post(
        "/training/runs",
        json={"dataset_version": "0.1.0"},
    )
    assert no_approval.status_code == 403
    assert "approval_id is required" in no_approval.json()["detail"]

    from apps.api.routers import training as training_router
    from apps.api.routers import workflows as workflows_router
    from apps.core.workflow import CentralWorkflowOrchestrator, WorkflowStepSpec

    isolated_engine = CentralWorkflowOrchestrator(
        db_path=tmp_path / "wf-missing-artifacts.db",
        work_dir=tmp_path / "wf-missing-artifacts-work",
        approval_secret="unit-test-approval-secret-minimum-32-chars",
    )
    monkeypatch.setattr(workflows_router, "_ENGINE", isolated_engine)
    monkeypatch.setattr(training_router, "get_workflow_engine", lambda: isolated_engine)

    try:
        wf_run, _ = isolated_engine.store.create_run(
            workflow_key="training.native_controlled_run",
            workflow_version="1.0.0",
            trigger_type="manual",
            trigger_payload={},
            steps=[{"step_key": "execute_training", "handler_key": "training.execute"}],
            requested_by_user_id=str(user.id),
        )
        pending = isolated_engine.governance.ensure_pending_approval(
            run_id=wf_run["id"],
            step=WorkflowStepSpec(
                step_key="execute_training",
                handler_key="training.execute",
                description="Execute training",
                tier="tier2_approval",
                action_type="training.execute",
            ),
            requested_by_user_id=str(user.id),
            scope="dataset:0.1.0",
        )
        approved = isolated_engine.governance.decide_approval(
            pending["id"],
            approve=True,
            approver_user_id=str(user.id),
            approver_role="admin",
            reason="Missing artifacts API test",
        )

        response = client.post(
            "/training/runs",
            json={"dataset_version": "0.1.0", "approval_id": approved["id"]},
        )

        assert response.status_code == 503
        assert "Native training dataset directory and tokenizer path are not configured." in response.json()["detail"]
        assert isolated_engine.store.get_approval(approved["id"])["status"] == "approved"
    finally:
        isolated_engine.shutdown(wait=True)


def test_orphaned_running_job_is_reported_failed(api_client):
    client, session_factory, user = api_client
    run_id = uuid.uuid4()
    with session_factory() as db:
        db.add(
            TrainingRun(
                id=run_id,
                owner_id=user.id,
                status="running",
                dataset_version="0.1.0",
                training_config={"max_steps": 20},
                model_config={"n_layers": 1},
            )
        )
        db.commit()

    response = client.get(f"/training/runs/{run_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_message"] == "Training worker is no longer active."


def test_status_and_telemetry_return_persisted_records(api_client, tmp_path, monkeypatch):
    client, session_factory, user = api_client
    training_root = tmp_path / "training"
    run_id = uuid.uuid4()
    run_dir = training_root / str(run_id)
    checkpoint_dir = run_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True)
    monkeypatch.setenv("ZYRQUEN_TRAINING_ROOT", str(training_root))

    with session_factory() as db:
        db.add(
            TrainingRun(
                id=run_id,
                owner_id=user.id,
                status="completed",
                dataset_version="0.1.0",
                training_config={"max_steps": 20},
                model_config={"n_layers": 1},
                result={"steps": 5},
            )
        )
        db.commit()

    monitor = TrainingMonitor(run_dir / "metrics.jsonl")
    monitor.log(step=5, loss=2.25, lr=0.001, tokens=32)

    def save_json(state, path):
        with open(path, "w", encoding="utf-8") as file:
            json.dump(state, file)

    manager = CheckpointManager(checkpoint_dir, save_fn=save_json)
    manager.save(5, {"step": 5})

    status_response = client.get(f"/training/runs/{run_id}")
    telemetry_response = client.get(f"/training/runs/{run_id}/telemetry")

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"
    assert telemetry_response.status_code == 200
    payload = telemetry_response.json()
    assert payload["metrics"][0]["loss"] == 2.25
    assert payload["checkpoints"][0]["step"] == 5
    assert payload["epochs_completed"] is None
