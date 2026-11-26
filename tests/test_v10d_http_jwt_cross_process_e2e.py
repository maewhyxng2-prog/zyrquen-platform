"""V10-D real HTTP/JWT approval and cross-process resume test.

A runner process creates a Tier-2 pending workflow. A separate API worker
process serves the actual FastAPI workflow router, authenticates JWTs, rejects
anonymous/non-admin callers, and resumes the run using the shared SQLite DB
and HMAC secret. The only registered step handler is synthetic: no training,
model mutation, or deployment occurs.
"""
from __future__ import annotations

import multiprocessing
import os
import tempfile
import time
import traceback
import unittest
import uuid
from pathlib import Path


os.environ.setdefault("ZYRQUEN_ENV", "unit_test")
os.environ.setdefault("DATABASE_URL", "sqlite://")

APPROVAL_SECRET = "v10d-http-cross-process-test-approval-secret"
JWT_SECRET = "v10d-http-cross-process-test-jwt-secret"
WORKFLOW_KEY = "training.v10d_http_cross_process_test"
WORKFLOW_VERSION = "1.0.0"
STEP_KEY = "synthetic_approval_step"
HANDLER_KEY = "test.v10d_http_synthetic"


def _definition():
    from apps.core.workflow.models import WorkflowDefinition, WorkflowStepSpec

    return WorkflowDefinition(
        workflow_key=WORKFLOW_KEY,
        version=WORKFLOW_VERSION,
        group_name="training",
        title="V10-D HTTP/JWT cross-process test",
        description="Synthetic governance test; does not invoke model training.",
        default_tier="tier2_approval",
        steps=(
            WorkflowStepSpec(
                step_key=STEP_KEY,
                handler_key=HANDLER_KEY,
                description="Synthetic no-training approval step",
                lane="control_ops",
                tier="tier2_approval",
                action_type="training.execute",
                max_attempts=1,
                estimated_ram_mb=1,
            ),
        ),
    )


def _api_http_worker(
    workflow_db_path: str,
    auth_db_path: str,
    run_id: str,
    approval_id: str,
    admin_token: str,
    user_token: str,
    result_queue,
) -> None:
    engine = None
    auth_engine = None
    try:
        os.environ.update(
            {
                "ZYRQUEN_V10D_APPROVAL_ENABLED": "1",
                "ZYRQUEN_WORKFLOW_DB_PATH": workflow_db_path,
                "ZYRQUEN_APPROVAL_SECRET": APPROVAL_SECRET,
                "ZYRQUEN_WORKFLOW_SCHEDULER": "0",
                "ZYRQUEN_WORKFLOW_RECOVERY": "0",
                "JWT_SECRET_KEY": JWT_SECRET,
            }
        )

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from apps.api.database import Base, get_db
        from apps.api.models import RevokedToken, User  # register auth tables
        from apps.api.routers import workflows
        from apps.api.security import get_current_user
        from apps.core.workflow.models import StepExecutionResult
        from apps.core.workflow.store import WorkflowStore

        auth_engine = create_engine(
            f"sqlite:///{auth_db_path}",
            connect_args={"check_same_thread": False},
        )
        SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=auth_engine,
        )

        def override_get_db():
            db = SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app = FastAPI()
        app.include_router(workflows.router)
        app.dependency_overrides[get_db] = override_get_db

        workflows._ENGINE = None
        engine = workflows.get_workflow_engine()
        definition = _definition()
        engine.registry.register_definition(definition)
        engine.store.upsert_definition(
            definition.workflow_key,
            definition.version,
            definition.group_name,
            definition.to_dag_spec(),
            definition.default_tier,
            definition.is_active,
        )

        def synthetic_handler(ctx, payload):
            return StepExecutionResult(
                verdict="PASS",
                summary="Synthetic handler completed; training was not invoked.",
                output={"synthetic_only": True, "training_invoked": False},
            )

        engine.registry.register_handler(HANDLER_KEY, synthetic_handler)

        decision_url = f"/v1/workflows/approvals/{approval_id}/decision"
        with TestClient(app) as client:
            anonymous = client.get("/v1/workflows/approvals")
            if anonymous.status_code != 401:
                raise AssertionError(f"anonymous request expected 401, got {anonymous.status_code}")

            ordinary_headers = {"Authorization": f"Bearer {user_token}"}
            non_admin_list = client.get("/v1/workflows/approvals", headers=ordinary_headers)
            if non_admin_list.status_code != 403:
                raise AssertionError(f"non-admin list expected 403, got {non_admin_list.status_code}")

            non_admin_decision = client.post(
                decision_url,
                headers=ordinary_headers,
                json={"approve": True, "reason": "must be denied"},
            )
            if non_admin_decision.status_code != 403:
                raise AssertionError(
                    f"non-admin decision expected 403, got {non_admin_decision.status_code}"
                )

            admin_headers = {"Authorization": f"Bearer {admin_token}"}
            listed = client.get("/v1/workflows/approvals", headers=admin_headers)
            if listed.status_code != 200:
                raise AssertionError(f"admin list expected 200, got {listed.status_code}")
            items = listed.json().get("items", [])
            match = next((item for item in items if item.get("id") == approval_id), None)
            if match is None:
                raise AssertionError("admin approval listing did not return the pending approval")
            if "signature_hmac" in match:
                raise AssertionError("approval API leaked signature_hmac")

            decision = client.post(
                decision_url,
                headers=admin_headers,
                json={"approve": True, "reason": "authorized HTTP/JWT integration test"},
            )
            if decision.status_code != 200:
                raise AssertionError(
                    f"admin decision expected 200, got {decision.status_code}: {decision.text}"
                )

        deadline = time.monotonic() + 15
        final_run = None
        while time.monotonic() < deadline:
            final_run = engine.store.get_run(run_id)
            if final_run and final_run.get("status") in {"COMPLETED", "FAILED", "BLOCKED"}:
                break
            time.sleep(0.05)

        approval = engine.store.get_approval(approval_id)
        final_run = engine.store.get_run(run_id)
        if not final_run or final_run.get("status") != "COMPLETED":
            raise AssertionError(f"workflow did not complete: {final_run}")
        if not approval or approval.get("status") != "consumed":
            raise AssertionError(f"approval was not consumed: {approval}")
        step = next(item for item in final_run["steps"] if item["step_key"] == STEP_KEY)
        if step.get("output", {}).get("training_invoked") is not False:
            raise AssertionError(f"synthetic safety assertion failed: {step.get('output')}")

        result_queue.put(
            {
                "status": "ok",
                "run_status": final_run["status"],
                "approval_status": approval["status"],
                "anonymous_status": anonymous.status_code,
                "non_admin_list_status": non_admin_list.status_code,
                "non_admin_decision_status": non_admin_decision.status_code,
                "admin_decision_status": decision.status_code,
                "training_invoked": False,
                "hmac_secret_configured": engine.governance._secret == APPROVAL_SECRET.encode("utf-8"),
            }
        )
    except Exception:
        result_queue.put({"status": "error", "traceback": traceback.format_exc()})
    finally:
        if engine is not None:
            engine.shutdown(wait=True)
        if auth_engine is not None:
            auth_engine.dispose()


class TestV10DHTTPJWTAndCrossProcessE2E(unittest.TestCase):
    def test_real_http_jwt_admin_gate_and_shared_hmac_resume_across_processes(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from apps.api.database import Base
        from apps.api.models import User
        from apps.api.security import create_access_token
        from apps.core.workflow.models import StepExecutionResult
        from apps.core.workflow.orchestrator import CentralWorkflowOrchestrator

        with tempfile.TemporaryDirectory() as td:
            workflow_db = str(Path(td) / "shared-workflows.db")
            auth_db = str(Path(td) / "auth-users.db")
            os.environ["JWT_SECRET_KEY"] = JWT_SECRET

            auth_engine = create_engine(
                f"sqlite:///{auth_db}",
                connect_args={"check_same_thread": False},
            )
            Base.metadata.create_all(auth_engine)
            SessionLocal = sessionmaker(bind=auth_engine)
            admin_id = uuid.uuid4()
            user_id = uuid.uuid4()
            with SessionLocal() as db:
                db.add_all(
                    [
                        User(
                            id=admin_id,
                            email="v10d-admin-test@example.invalid",
                            password_hash="not-used-by-bearer-auth",
                            role="admin",
                            is_active=True,
                        ),
                        User(
                            id=user_id,
                            email="v10d-user-test@example.invalid",
                            password_hash="not-used-by-bearer-auth",
                            role="user",
                            is_active=True,
                        ),
                    ]
                )
                db.commit()
            auth_engine.dispose()

            admin_token = create_access_token(str(admin_id))
            user_token = create_access_token(str(user_id))

            runner = CentralWorkflowOrchestrator(
                db_path=workflow_db,
                work_dir=td,
                approval_secret=APPROVAL_SECRET,
            )
            try:
                definition = _definition()
                runner.registry.register_definition(definition)
                runner.store.upsert_definition(
                    definition.workflow_key,
                    definition.version,
                    definition.group_name,
                    definition.to_dag_spec(),
                    definition.default_tier,
                    definition.is_active,
                )

                paused = runner.trigger_workflow(
                    WORKFLOW_KEY,
                    version=WORKFLOW_VERSION,
                    trigger_type="manual",
                    payload={"test_only": True},
                    requested_by_user_id=str(user_id),
                    actor_id="test-runner",
                )
                self.assertEqual(paused["status"], "WAITING_APPROVAL")
                self.assertEqual(len(paused["approvals"]), 1)
                approval_id = paused["approvals"][0]["id"]
                run_id = paused["id"]
            finally:
                runner.shutdown(wait=True)

            ctx = multiprocessing.get_context("spawn")
            result_queue = ctx.Queue()
            api_process = ctx.Process(
                target=_api_http_worker,
                args=(
                    workflow_db,
                    auth_db,
                    run_id,
                    approval_id,
                    admin_token,
                    user_token,
                    result_queue,
                ),
            )
            api_process.start()
            api_process.join(timeout=35)
            if api_process.is_alive():
                api_process.terminate()
                api_process.join()
                self.fail("HTTP API worker process timed out")
            self.assertEqual(api_process.exitcode, 0)

            child_result = result_queue.get(timeout=5)
            self.assertEqual(child_result.get("status"), "ok", child_result)
            self.assertEqual(child_result["anonymous_status"], 401)
            self.assertEqual(child_result["non_admin_list_status"], 403)
            self.assertEqual(child_result["non_admin_decision_status"], 403)
            self.assertEqual(child_result["admin_decision_status"], 200)
            self.assertEqual(child_result["run_status"], "COMPLETED")
            self.assertEqual(child_result["approval_status"], "consumed")
            self.assertTrue(child_result["hmac_secret_configured"])
            self.assertFalse(child_result["training_invoked"])


if __name__ == "__main__":
    unittest.main()
