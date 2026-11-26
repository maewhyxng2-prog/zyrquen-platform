"""V10-D Tier-2 governance runtime tests across independently opened stores."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

# API imports activate the database safety guard. Explicitly select the
# SQLite-only unit_test environment before importing any API modules.
os.environ.setdefault("ZYRQUEN_ENV", "unit_test")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi import HTTPException

from apps.api.routers.admin import require_admin
from apps.core.workflow.governance import WorkflowGovernance
from apps.core.workflow.models import ApprovalViolationError, WorkflowStepSpec
from apps.core.workflow.store import WorkflowStore


SECRET = "unit-test-shared-v10d-approval-secret"
WORKFLOW_KEY = "training.v10d_closure_run"
STEP = WorkflowStepSpec(
    step_key="execute_v10d_training",
    handler_key="v10d.train_execute",
    description="Test-only gated step",
    tier="tier2_approval",
    action_type="training.execute",
)
SCOPE = f"{WORKFLOW_KEY}:{STEP.step_key}"


def _create_pending(store: WorkflowStore, governance: WorkflowGovernance, *, ttl_minutes: int = 120):
    run, created = store.create_run(
        workflow_key=WORKFLOW_KEY,
        workflow_version="1.0.0",
        trigger_type="manual",
        trigger_payload={"test_only": True},
        steps=[STEP.to_dict()],
        requested_by_user_id="requester-test",
    )
    if not created:
        raise AssertionError("Test workflow run unexpectedly deduplicated")
    approval = governance.ensure_pending_approval(
        run_id=run["id"],
        step=STEP,
        requested_by_user_id="requester-test",
        scope=SCOPE,
        ttl_minutes=ttl_minutes,
        reason="Automated governance test only",
    )
    return run, approval


class TestV10DTier2GovernanceRuntime(unittest.TestCase):
    def test_authenticated_admin_gate_rejects_non_admin(self):
        with self.assertRaises(HTTPException) as exc:
            require_admin(SimpleNamespace(role="user"))
        self.assertEqual(exc.exception.status_code, 403)
        self.assertEqual(require_admin(SimpleNamespace(role="admin")).role, "admin")

    def test_api_and_runner_store_instances_share_hmac_and_consume_once(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "shared-approval.db"
            api_store = WorkflowStore(db_path)
            runner_store = WorkflowStore(db_path)
            api_governance = WorkflowGovernance(api_store, secret=SECRET)
            runner_governance = WorkflowGovernance(runner_store, secret=SECRET)

            run, approval = _create_pending(api_store, api_governance)
            decided = api_governance.decide_approval(
                approval["id"],
                approve=True,
                approver_user_id="authenticated-admin-test-id",
                approver_role="admin",
                reason="Approved by test fixture; no training handler is invoked",
            )
            self.assertEqual(decided["status"], "approved")

            consumed = runner_governance.verify_and_consume_by_id(
                approval["id"],
                expected_action_type="training.execute",
                expected_run_id=run["id"],
                expected_step_key=STEP.step_key,
                expected_scope=SCOPE,
            )
            self.assertEqual(consumed["status"], "consumed")
            self.assertIsNotNone(consumed["consumed_at"])

            with self.assertRaises(ApprovalViolationError):
                api_governance.verify_and_consume_by_id(
                    approval["id"],
                    expected_action_type="training.execute",
                    expected_run_id=run["id"],
                    expected_step_key=STEP.step_key,
                    expected_scope=SCOPE,
                )

    def test_shared_store_rejects_wrong_hmac_secret(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "shared-approval.db"
            api_store = WorkflowStore(db_path)
            runner_store = WorkflowStore(db_path)
            api_governance = WorkflowGovernance(api_store, secret=SECRET)
            wrong_runner_governance = WorkflowGovernance(runner_store, secret="wrong-secret")

            run, approval = _create_pending(api_store, api_governance)
            api_governance.decide_approval(
                approval["id"],
                approve=True,
                approver_user_id="authenticated-admin-test-id",
                approver_role="admin",
            )
            with self.assertRaises(ApprovalViolationError):
                wrong_runner_governance.verify_and_consume_by_id(
                    approval["id"],
                    expected_action_type="training.execute",
                    expected_run_id=run["id"],
                    expected_step_key=STEP.step_key,
                    expected_scope=SCOPE,
                )
            self.assertEqual(runner_store.get_approval(approval["id"])["status"], "approved")

    def test_admin_role_is_required_to_issue_approval(self):
        with tempfile.TemporaryDirectory() as td:
            store = WorkflowStore(Path(td) / "approval.db")
            governance = WorkflowGovernance(store, secret=SECRET)
            _, approval = _create_pending(store, governance)
            with self.assertRaises(ApprovalViolationError):
                governance.decide_approval(
                    approval["id"],
                    approve=True,
                    approver_user_id="ordinary-user",
                    approver_role="user",
                )
            self.assertEqual(store.get_approval(approval["id"])["status"], "pending")

    def test_expired_approval_cannot_be_issued(self):
        with tempfile.TemporaryDirectory() as td:
            store = WorkflowStore(Path(td) / "approval.db")
            governance = WorkflowGovernance(store, secret=SECRET)
            _, approval = _create_pending(store, governance, ttl_minutes=-1)
            with self.assertRaises(ApprovalViolationError):
                governance.decide_approval(
                    approval["id"],
                    approve=True,
                    approver_user_id="authenticated-admin-test-id",
                    approver_role="admin",
                )
            self.assertEqual(store.get_approval(approval["id"])["status"], "expired")


if __name__ == "__main__":
    unittest.main()
