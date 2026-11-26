"""FastAPI integration tests for Dataset Status API and Training Readiness/List/Gate APIs."""

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.database import Base, get_db
from apps.api.main import app
from apps.api.models import User
from apps.api.routers import training as training_router
from apps.api.security import get_current_user
from apps.api.training_models import TrainingRun
from apps.core.native.dataset import SCHEMA
from apps.core.native.tokenizer import BASE_VOCAB, ZyrquenTokenizer


def _build_valid_dataset(target_dir: Path, version: str = "0.1.0") -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    splits = {
        "train": json.dumps({"input": "alpha TR_E1", "target": "ok TR_E1"}) + "\n",
        "validation": json.dumps({"input": "beta VA_E2", "target": "ok VA_E2"}) + "\n",
        "test": json.dumps({"input": "gamma TE_E3", "target": "ok TE_E3"}) + "\n",
    }
    files = {}
    hashes = []
    for name, body in splits.items():
        data = body.encode("utf-8")
        (target_dir / f"{name}.jsonl").write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        files[f"{name}.jsonl"] = {"documents": 1, "sha256": sha}
        hashes.append(sha)
    content_sha = hashlib.sha256("".join(hashes).encode("utf-8")).hexdigest()
    manifest = {
        "schema": SCHEMA,
        "version": version,
        "content_sha256": content_sha,
        "sources": {"unit": {"license": "CC-BY-4.0", "sha256": content_sha}},
        "files": files,
    }
    (target_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return target_dir


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'datasets-training-test.db'}",
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
    monkeypatch.setenv("ZYRQUEN_TRAINING_ADMIN_EMAILS", "training-admin@example.com")
    monkeypatch.delenv("ZYRQUEN_DATASET_DIR", raising=False)
    monkeypatch.delenv("ZYRQUEN_DATASET_ROOT", raising=False)
    monkeypatch.delenv("ZYRQUEN_TOKENIZER_PATH", raising=False)

    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        yield client, TestingSession, test_user, tmp_path

    app.dependency_overrides.clear()
    engine.dispose()



def test_workflow_engine_recreated_after_shutdown(tmp_path, monkeypatch):
    from apps.api.routers import workflows as workflows_router
    from apps.core.workflow import CentralWorkflowOrchestrator

    closed_engine = CentralWorkflowOrchestrator(
        db_path=tmp_path / "closed-workflow.db",
        work_dir=tmp_path / "closed-workflow-work",
        approval_secret="unit-test-approval-secret-minimum-32-chars",
    )
    closed_engine.shutdown(wait=True)
    monkeypatch.setattr(workflows_router, "_ENGINE", closed_engine)

    replacement = workflows_router.get_workflow_engine()
    assert replacement is not closed_engine
    assert replacement.is_closed is False
    replacement.shutdown(wait=True)


def test_dataset_status_requires_authentication(api_client):
    client, _, _, _ = api_client
    app.dependency_overrides.pop(get_current_user)
    resp = client.get("/v1/datasets/status")
    assert resp.status_code == 401


def test_dataset_status_unconfigured_vs_verified(api_client, monkeypatch):
    client, _, _, tmp_path = api_client
    unconfigured = client.get("/v1/datasets/status")
    assert unconfigured.status_code == 200
    assert unconfigured.json()["configured"] is False
    assert unconfigured.json()["status"] == "not_configured"

    unconfigured_ver = client.get("/v1/datasets/0.1.0/status")
    assert unconfigured_ver.status_code == 503

    root = tmp_path / "datasets"
    ds = _build_valid_dataset(root / "0.1.0", version="0.1.0")
    monkeypatch.setenv("ZYRQUEN_DATASET_DIR", str(ds))
    monkeypatch.setenv("ZYRQUEN_DATASET_ROOT", str(root))

    ready = client.get("/v1/datasets/status")
    assert ready.status_code == 200
    assert ready.json()["configured"] is True
    assert ready.json()["status"] == "ready"
    assert ready.json()["active_dataset"]["verified"] is True

    ver = client.get("/v1/datasets/0.1.0/status")
    assert ver.status_code == 200
    assert ver.json()["version"] == "0.1.0"
    assert ver.json()["verified"] is True

    missing = client.get("/v1/datasets/9.9.9/status")
    assert missing.status_code == 404

    invalid = client.get("/v1/datasets/v1..2/status")
    assert invalid.status_code == 422


def test_training_readiness_and_runs_list(api_client, monkeypatch):
    client, session_factory, user, tmp_path = api_client
    run_id = uuid.uuid4()
    with session_factory() as db:
        db.add(
            TrainingRun(
                id=run_id,
                owner_id=user.id,
                status="running",
                dataset_version="0.1.0",
                training_config={"max_steps": 10},
                model_config={"n_layers": 1},
            )
        )
        db.commit()

    readiness = client.get("/training/readiness")
    assert readiness.status_code == 200
    body = readiness.json()
    assert body["configured"] is False
    assert body["status"] == "not_configured"
    assert body["dataset_verified"] is False
    assert "runtime_ready" in body
    assert "worker_ready" in body
    assert body["tier2_approval_required"] is True
    assert body["is_training_admin"] is True
    assert len(body["reasons"]) >= 1

    runs_resp = client.get("/training/runs")
    assert runs_resp.status_code == 200
    items = runs_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(run_id)
    assert items[0]["status"] == "failed"

    monkeypatch.setenv("ZYRQUEN_TRAINING_ADMIN_EMAILS", "other@example.com")
    forbidden = client.get("/training/runs")
    assert forbidden.status_code == 403


def test_training_start_enforces_tier2_approval_when_artifacts_configured(api_client, monkeypatch):
    client, _, user, tmp_path = api_client
    ds = _build_valid_dataset(tmp_path / "ds", version="0.1.0")
    tok = tmp_path / "tokenizer.json"
    ZyrquenTokenizer.train(
        ["alpha TR_E1 ok beta VA_E2 ok " * 8],
        vocab_size=BASE_VOCAB + 8,
    ).save(tok)

    monkeypatch.setattr(training_router.jobs._orchestrator, "dataset_dir", None)
    monkeypatch.setattr(training_router.jobs._orchestrator, "tokenizer_path", None)

    # Even when dataset/tokenizer paths are NOT configured, missing/forged approval MUST be rejected (403), never 503 bypass
    unconfigured_no_approval = client.post(
        "/training/runs",
        json={"dataset_version": "0.1.0"},
    )
    assert unconfigured_no_approval.status_code == 403
    assert "approval_id is required" in unconfigured_no_approval.json()["detail"]

    unconfigured_forged = client.post(
        "/training/runs",
        json={"dataset_version": "0.1.0", "approval_id": "forged-id"},
    )
    assert unconfigured_forged.status_code == 403
    assert "Tier-2 training approval rejected" in unconfigured_forged.json()["detail"]

    monkeypatch.setattr(training_router.jobs._orchestrator, "dataset_dir", ds)
    monkeypatch.setattr(training_router.jobs._orchestrator, "tokenizer_path", tok)
    monkeypatch.setattr(training_router.jobs._orchestrator, "training_root", tmp_path / "runs")

    missing_approval = client.post(
        "/training/runs",
        json={"dataset_version": "0.1.0"},
    )
    assert missing_approval.status_code == 403
    assert "approval_id is required" in missing_approval.json()["detail"]

    forged_approval = client.post(
        "/training/runs",
        json={"dataset_version": "0.1.0", "approval_id": "forged-id"},
    )
    assert forged_approval.status_code == 403
    assert "Tier-2 training approval rejected" in forged_approval.json()["detail"]

    # Even if tokenizer/dataset prepare() would fail with 503, forged approval must still return 403
    bad_tok = tmp_path / "bad_tokenizer.json"
    bad_tok.write_text('{"schema": "zyrquen.tokenizer.v2"}', encoding="utf-8")
    monkeypatch.setattr(training_router.jobs._orchestrator, "tokenizer_path", bad_tok)
    forged_over_bad_tok = client.post(
        "/training/runs",
        json={"dataset_version": "0.1.0", "approval_id": "forged-id"},
    )
    assert forged_over_bad_tok.status_code == 403
    assert "Tier-2 training approval rejected" in forged_over_bad_tok.json()["detail"]

    # Valid Tier-2 approval must NOT be consumed when worker is busy (409) or prepare() fails (503)
    from apps.core.workflow import CentralWorkflowOrchestrator, WorkflowStepSpec
    from apps.api.routers import workflows as workflows_router

    isolated_engine = CentralWorkflowOrchestrator(
        db_path=tmp_path / "wf-gate.db",
        work_dir=tmp_path / "wf-work",
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
            reason="API gate test",
        )

        # Wrong dataset scope must be rejected with 403
        wrong_scope = client.post(
            "/training/runs",
            json={"dataset_version": "9.9.9", "approval_id": approved["id"]},
        )
        assert wrong_scope.status_code == 403
        assert isolated_engine.store.get_approval(approved["id"])["status"] == "approved"

        # Approval bound to non-training step handler must be rejected with 403
        bad_step_run, _ = isolated_engine.store.create_run(
            workflow_key="dataset.governed_ingest",
            workflow_version="1.0.0",
            trigger_type="manual",
            trigger_payload={},
            steps=[{"step_key": "wrong_step", "handler_key": "dataset.ingest"}],
            requested_by_user_id=str(user.id),
        )
        wrong_step_pending = isolated_engine.governance.ensure_pending_approval(
            run_id=bad_step_run["id"],
            step=WorkflowStepSpec(
                step_key="wrong_step",
                handler_key="dataset.ingest",
                description="Wrong step",
                tier="tier2_approval",
                action_type="training.execute",
            ),
            requested_by_user_id=str(user.id),
            scope="dataset:0.1.0",
        )
        wrong_step_approved = isolated_engine.governance.decide_approval(
            wrong_step_pending["id"],
            approve=True,
            approver_user_id=str(user.id),
            approver_role="admin",
            reason="Wrong step probe",
        )
        wrong_step_resp = client.post(
            "/training/runs",
            json={"dataset_version": "0.1.0", "approval_id": wrong_step_approved["id"]},
        )
        assert wrong_step_resp.status_code == 403

        # 503 during prepare() preserves approved status without burning single-use token
        resp_503 = client.post(
            "/training/runs",
            json={"dataset_version": "0.1.0", "approval_id": approved["id"]},
        )
        assert resp_503.status_code == 503
        assert isolated_engine.store.get_approval(approved["id"])["status"] == "approved"

        # 409 busy preserves approved status without burning single-use token
        monkeypatch.setattr(training_router.jobs._orchestrator, "tokenizer_path", tok)
        monkeypatch.setattr(training_router.jobs, "is_busy", lambda: True)
        resp_409 = client.post(
            "/training/runs",
            json={"dataset_version": "0.1.0", "approval_id": approved["id"]},
        )
        assert resp_409.status_code == 409
        assert isolated_engine.store.get_approval(approved["id"])["status"] == "approved"
    finally:
        isolated_engine.shutdown(wait=True)


def _build_v11_dataset(target_dir: Path, *, leak: bool = False) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    splits = {
        "train": json.dumps({"input": "rule TR_E11", "target": "ok TR_E11", "split": "train"}) + "\n",
        "validation": json.dumps({"input": "rule VA_E22", "target": "ok VA_E22", "split": "validation"}) + "\n",
        "unseen": json.dumps(
            {
                "input": f"rule {'TR_E11' if leak else 'UN_E33'}",
                "target": f"ok {'TR_E11' if leak else 'UN_E33'}",
                "split": "unseen",
            }
        )
        + "\n",
        "ood": json.dumps({"input": "rule OO_E44", "target": "ok OO_E44", "split": "ood"}) + "\n",
    }
    files = {}
    hashes = []
    for name, body in splits.items():
        data = body.encode("utf-8")
        (target_dir / f"{name}.jsonl").write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        files[f"{name}.jsonl"] = {"documents": 1, "sha256": sha}
        hashes.append(sha)
    content_sha = hashlib.sha256("".join(hashes).encode("utf-8")).hexdigest()
    manifest = {
        "schema": SCHEMA,
        "dataset": "nagi_v11",
        "version": "nagi_v11",
        "content_sha256": content_sha,
        "sources": {"unit": {"license": "CC-BY-4.0", "sha256": content_sha}},
        "files": files,
    }
    (target_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return target_dir


def test_training_readiness_enforces_v11_four_split_and_leakage_detection(api_client, monkeypatch):
    client, _, _, tmp_path = api_client
    tok = tmp_path / "tokenizer.json"
    ZyrquenTokenizer.train(["rule TR_E11 ok " * 10], vocab_size=BASE_VOCAB + 8).save(tok)
    monkeypatch.setenv("ZYRQUEN_TOKENIZER_PATH", str(tok))
    monkeypatch.setattr(training_router.jobs._orchestrator, "training_root", tmp_path / "runs")

    # 1. 3-split dataset is rejected by /training/readiness V11 4-split gate
    ds_v10 = _build_valid_dataset(tmp_path / "ds_v10", version="0.1.0")
    monkeypatch.setenv("ZYRQUEN_DATASET_DIR", str(ds_v10))
    res_3split = client.get("/training/readiness").json()
    assert res_3split["dataset_configured"] is True
    assert res_3split["four_split_present"] is False
    assert res_3split["dataset_verified"] is False
    assert res_3split["dataset"]["four_split_enforced"] is True
    assert any("4-split" in r for r in res_3split["reasons"])

    # 2. Leaked 4-split dataset fails DataAdapter.detect_leakage
    ds_leaked = _build_v11_dataset(tmp_path / "ds_v11_leaked", leak=True)
    monkeypatch.setenv("ZYRQUEN_DATASET_DIR", str(ds_leaked))
    res_leaked = client.get("/training/readiness").json()
    assert res_leaked["four_split_present"] is True
    assert res_leaked["dataset_verified"] is False
    assert res_leaked["dataset"]["leakage_check"]["passed"] is False

    # 3. Clean V11 4-split dataset passes DataAdapter verification, leakage check, and orchestrator preflight
    #    but MUST remain status='not_ready' without an active signed Tier-2 training.execute approval.
    ds_clean = _build_v11_dataset(tmp_path / "ds_v11_clean", leak=False)
    monkeypatch.setenv("ZYRQUEN_DATASET_DIR", str(ds_clean))
    res_clean = client.get("/training/readiness").json()
    assert res_clean["four_split_present"] is True
    assert res_clean["dataset_verified"] is True
    assert res_clean["dataset"]["leakage_check"]["passed"] is True
    assert res_clean["tokenizer"]["valid"] is True
    assert res_clean["preflight"]["passed"] is True
    assert res_clean["preflight"]["resource_limits_checked"] is True
    assert res_clean["approval_ready"] is False
    assert res_clean["status"] == "not_ready"


def test_training_readiness_requires_active_signed_approval_for_ready_status(api_client, monkeypatch):
    from apps.api.routers import workflows as workflows_router
    from apps.core.workflow import CentralWorkflowOrchestrator, WorkflowStepSpec

    client, _, user, tmp_path = api_client
    tok = tmp_path / "tokenizer.json"
    ZyrquenTokenizer.train(["rule TR_E11 ok " * 10], vocab_size=BASE_VOCAB + 8).save(tok)
    ds_clean = _build_v11_dataset(tmp_path / "ds_v11_ready", leak=False)
    monkeypatch.setenv("ZYRQUEN_TOKENIZER_PATH", str(tok))
    monkeypatch.setenv("ZYRQUEN_DATASET_DIR", str(ds_clean))
    monkeypatch.setattr(training_router.jobs._orchestrator, "training_root", tmp_path / "runs")

    isolated_engine = CentralWorkflowOrchestrator(
        db_path=tmp_path / "wf-ready.db",
        work_dir=tmp_path / "wf-ready-work",
        approval_secret="unit-test-approval-secret-minimum-32-chars",
    )
    monkeypatch.setattr(workflows_router, "_ENGINE", isolated_engine)
    monkeypatch.setattr(training_router, "get_workflow_engine", lambda: isolated_engine)
    try:
        before = client.get("/training/readiness").json()
        assert before["approval_ready"] is False
        assert before["status"] == "not_ready"

        # Approval bound to a DIFFERENT dataset version must NOT mark readiness ready
        other_run, _ = isolated_engine.store.create_run(
            workflow_key="training.native_controlled_run",
            workflow_version="1.0.0",
            trigger_type="manual",
            trigger_payload={},
            steps=[{"step_key": "execute_training", "handler_key": "training.execute"}],
            requested_by_user_id=str(user.id),
        )
        other_pending = isolated_engine.governance.ensure_pending_approval(
            run_id=other_run["id"],
            step=WorkflowStepSpec(
                step_key="execute_training",
                handler_key="training.execute",
                description="Execute training for other dataset",
                tier="tier2_approval",
                action_type="training.execute",
            ),
            requested_by_user_id=str(user.id),
            scope="dataset:other_version",
        )
        isolated_engine.governance.decide_approval(
            other_pending["id"],
            approve=True,
            approver_user_id=str(user.id),
            approver_role="admin",
            reason="Mismatched dataset probe",
        )
        mismatch_readiness = client.get("/training/readiness").json()
        assert mismatch_readiness["dataset"]["dataset_version"] == "nagi_v11"
        assert mismatch_readiness["approval_ready"] is False
        assert mismatch_readiness["status"] == "not_ready"

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
            scope="dataset:nagi_v11",
        )
        isolated_engine.governance.decide_approval(
            pending["id"],
            approve=True,
            approver_user_id=str(user.id),
            approver_role="admin",
            reason="Readiness test approval",
        )
        after = client.get("/training/readiness").json()
        assert after["approval_secret_configured"] is True
        assert after["approval_ready"] is True
        assert after["approved_training_approvals"] == 1
        assert after["status"] == "ready"
    finally:
        isolated_engine.shutdown(wait=True)


def test_dataset_ingest_enforces_provenance_leakage_and_no_overwrite(api_client, monkeypatch):
    from apps.api.routers import datasets as datasets_router
    from apps.api.routers import workflows as workflows_router
    from apps.core.workflow import CentralWorkflowOrchestrator

    client, _, user, tmp_path = api_client
    root = tmp_path / "datasets_ingest_root"
    root.mkdir()
    monkeypatch.setenv("ZYRQUEN_DATASET_ROOT", str(root))

    isolated_engine = CentralWorkflowOrchestrator(
        db_path=tmp_path / "wf-ingest.db",
        work_dir=tmp_path / "wf-ingest-work",
        approval_secret="unit-test-approval-secret-minimum-32-chars",
    )
    monkeypatch.setattr(workflows_router, "_ENGINE", isolated_engine)
    monkeypatch.setattr(datasets_router, "get_workflow_engine", lambda: isolated_engine)
    try:
        base_splits = {
            "train": [{"input": "rule TR_E11", "target": "ok TR_E11"}],
            "validation": [{"input": "rule VA_E22", "target": "ok VA_E22"}],
            "unseen": [{"input": "rule UN_E33", "target": "ok UN_E33"}],
            "ood": [{"input": "rule OO_E44", "target": "ok OO_E44"}],
        }

        # Missing Approval Gate ticket must be rejected with 403
        missing_ticket = client.post(
            "/v1/datasets/ingest",
            json={
                "dataset_version": "1.0.0",
                "source_name": "verified_field_notes",
                "license": "CC-BY-4.0",
                "provenance": "human_curated_native_corpus",
                "splits": base_splits,
            },
        )
        assert missing_ticket.status_code == 403
        assert not (root / "1.0.0").exists()

        # Forged Approval Gate ticket must be rejected with 403
        forged_ticket = client.post(
            "/v1/datasets/ingest",
            json={
                "dataset_version": "1.0.0",
                "source_name": "verified_field_notes",
                "license": "CC-BY-4.0",
                "provenance": "human_curated_native_corpus",
                "approval_id": "forged-ticket-id",
                "splits": base_splits,
            },
        )
        assert forged_ticket.status_code == 403
        assert not (root / "1.0.0").exists()

        # Issue and approve a valid Tier-2 dataset.ingest ticket
        wf_run = isolated_engine.trigger_workflow(
            "dataset.governed_ingest",
            payload={"dataset_version": "1.0.0"},
            requested_by_user_id=str(user.id),
            actor_id=user.email,
        )
        ticket_id = wf_run["pending_approval_id"]
        isolated_engine.governance.decide_approval(
            ticket_id,
            approve=True,
            approver_user_id=str(user.id),
            approver_role="admin",
            reason="Dataset ingest API test",
        )

        # Reject synthetic/external provenance without consuming the valid ticket
        bad_prov = client.post(
            "/v1/datasets/ingest",
            json={
                "dataset_version": "1.0.0",
                "source_name": "synthetic_source",
                "license": "CC-BY-4.0",
                "provenance": "generated_by_gpt",
                "approval_id": ticket_id,
                "splits": base_splits,
            },
        )
        assert bad_prov.status_code == 422
        assert not (root / "1.0.0").exists()
        assert isolated_engine.store.get_approval(ticket_id)["status"] == "approved"

        # Reject cross-split entity leakage without persisting or burning the ticket
        leaked = client.post(
            "/v1/datasets/ingest",
            json={
                "dataset_version": "1.0.0",
                "source_name": "verified_field_notes",
                "license": "CC-BY-4.0",
                "provenance": "human_curated_native_corpus",
                "approval_id": ticket_id,
                "splits": {
                    "train": [{"input": "rule TR_E11", "target": "ok TR_E11"}],
                    "validation": [{"input": "rule VA_E22", "target": "ok VA_E22"}],
                    "unseen": [{"input": "rule TR_E11 extra", "target": "ok TR_E11"}],
                    "ood": [{"input": "rule OO_E44", "target": "ok OO_E44"}],
                },
            },
        )
        assert leaked.status_code == 422
        assert not (root / "1.0.0").exists()
        assert isolated_engine.store.get_approval(ticket_id)["status"] == "approved"

        # Clean V11 4-split dataset succeeds, marks status='ready', and consumes single-use ticket
        clean_payload = {
            "dataset_version": "1.0.0",
            "source_name": "verified_field_notes",
            "license": "CC-BY-4.0",
            "provenance": "human_curated_native_corpus",
            "approval_id": ticket_id,
            "splits": base_splits,
        }
        created = client.post("/v1/datasets/ingest", json=clean_payload)
        assert created.status_code == 201
        body = created.json()
        assert body["verified"] is True
        assert body["status"] == "ready"
        assert body["approval_gate_verified"] is True
        assert body["four_split_compliant"] is True
        assert body["v11_leakage_check"]["passed"] is True
        assert body["licensed_sources_count"] == 1
        assert isolated_engine.store.get_approval(ticket_id)["status"] == "consumed"

        # Re-using consumed ticket must be rejected with 403
        reused = client.post("/v1/datasets/ingest", json=clean_payload)
        assert reused.status_code == 403
    finally:
        isolated_engine.shutdown(wait=True)


