"""Regression tests: Tier-2 approval path and trusted estimated_params resolution."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from apps.core.workflow.governance import ApprovalViolationError
from apps.core.workflow.models import (
    StepExecutionResult,
    WorkflowDefinition,
    WorkflowStepSpec,
    WorkflowValidationError,
)
from apps.core.workflow.orchestrator import CentralWorkflowOrchestrator
from apps.core.workflow.param_budget import resolve_estimated_params
from apps.core.workflow.resource_guard import MAX_CPU_MODEL_PARAMETERS, WorkflowResourceGuard

OVER_CAP = MAX_CPU_MODEL_PARAMETERS + 1


def _recording_handler(calls: list[dict[str, Any]]):
    def handler(ctx, payload):
        calls.append(dict(payload or {}))
        return StepExecutionResult(verdict="PASS", summary="ran", output={"ran": True})

    return handler


def _single_step_definition(key: str, handler_key: str, **step_kwargs: Any) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_key=key,
        version="1.0.0",
        group_name="training",
        title=key,
        description="regression fixture",
        steps=(WorkflowStepSpec(step_key="train", handler_key=handler_key, **step_kwargs),),
    )


class TestTier2Gate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.orch = CentralWorkflowOrchestrator(
            db_path=self.tmp_dir / "wf.db",
            work_dir=self.tmp_dir,
            approval_secret="unit-test-secret-key-at-least-32-bytes",
        )

    def tearDown(self) -> None:
        self.orch.shutdown(wait=True)
        self._tmp.cleanup()

    def _gated_workflow(self, key: str) -> None:
        self.orch.registry.register_handler(
            key,
            lambda ctx, payload: StepExecutionResult(
                verdict="PASS",
                summary="tier-2 executed",
                output={"consumed_approval_id": (ctx.get("consumed_approval") or {}).get("id")},
            ),
        )
        self.orch.registry.register_definition(
            _single_step_definition(
                key,
                key,
                description="Needs admin approval",
                tier="tier2_approval",
                action_type="training.execute",
            )
        )

    def test_tier2_request_pauses_without_reason_kwarg(self) -> None:
        self._gated_workflow("test.tier2_regression")
        run = self.orch.trigger_workflow("test.tier2_regression", requested_by_user_id="user-1")
        self.assertEqual(run["status"], "WAITING_APPROVAL")
        approval_id = run["approvals"][0]["id"]
        resumed = self.orch.decide_approval_and_resume(
            approval_id,
            approve=True,
            approver_user_id="admin-1",
            approver_role="admin",
            reason="Verified safety gate",
        )
        self.assertEqual(resumed["status"], "COMPLETED")
        self.assertEqual(resumed["steps"][0]["output"]["consumed_approval_id"], approval_id)
        self.assertEqual(self.orch.store.get_approval(approval_id)["status"], "consumed")

    def test_non_admin_cannot_approve(self) -> None:
        self._gated_workflow("test.tier2_rbac")
        run = self.orch.trigger_workflow("test.tier2_rbac", requested_by_user_id="user-1")
        with self.assertRaises(ApprovalViolationError):
            self.orch.decide_approval_and_resume(
                run["approvals"][0]["id"],
                approve=True,
                approver_user_id="user-1",
                approver_role="user",
            )

    def test_forged_hmac_still_blocks(self) -> None:
        self._gated_workflow("test.tier2_tamper")
        run = self.orch.trigger_workflow("test.tier2_tamper")
        approval_id = run["approvals"][0]["id"]
        self.orch.store.set_approval_decision(
            approval_id,
            status="approved",
            approved_by_user_id="attacker",
            signature_hmac="0" * 64,
        )
        self.orch.store.update_step(run["id"], "train", status="PENDING")
        self.orch.store.update_run(run["id"], status="PENDING")
        resumed = self.orch.execute_run(run["id"])
        steps = {s["step_key"]: s for s in resumed["steps"]}
        self.assertEqual(steps["train"]["status"], "BLOCKED")
        self.assertNotEqual(resumed["status"], "COMPLETED")


class TestEstimatedParamsBudget(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.orch = CentralWorkflowOrchestrator(
            db_path=self.tmp_dir / "wf.db",
            work_dir=self.tmp_dir,
            approval_secret="unit-test-secret-key-at-least-32-bytes",
        )

    def tearDown(self) -> None:
        self.orch.shutdown(wait=True)
        self._tmp.cleanup()

    def test_step_config_over_cap_blocks_before_handler(self) -> None:
        calls: list[dict[str, Any]] = []
        self.orch.registry.register_handler("test.cfg_handler", _recording_handler(calls))
        self.orch.registry.register_definition(
            _single_step_definition("test.cfg_overflow", "test.cfg_handler", estimated_params=OVER_CAP)
        )
        run = self.orch.trigger_workflow("test.cfg_overflow")
        steps = {s["step_key"]: s for s in run["steps"]}
        self.assertEqual(run["status"], "BLOCKED")
        self.assertEqual(steps["train"]["error_code"], "resource_blocked")
        self.assertIn("parameter_budget_exceeded", run["error_message"])
        self.assertEqual(calls, [])

    def test_step_config_within_cap_runs_handler(self) -> None:
        calls: list[dict[str, Any]] = []
        self.orch.registry.register_handler("test.cfg_ok_handler", _recording_handler(calls))
        self.orch.registry.register_definition(
            _single_step_definition("test.cfg_ok", "test.cfg_ok_handler", estimated_params=1_000)
        )
        self.assertEqual(self.orch.trigger_workflow("test.cfg_ok")["status"], "COMPLETED")
        self.assertEqual(len(calls), 1)

    def test_prior_step_output_blocks_dependent_step(self) -> None:
        calls: list[dict[str, Any]] = []
        self.orch.registry.register_handler(
            "test.preflight_est",
            lambda ctx, payload: StepExecutionResult(
                verdict="PASS", summary="preflight", output={"estimated_params": OVER_CAP}
            ),
        )
        self.orch.registry.register_handler("test.train_est", _recording_handler(calls))
        self.orch.registry.register_definition(
            WorkflowDefinition(
                workflow_key="test.prior_output_budget",
                version="1.0.0",
                group_name="training",
                title="prior output budget",
                description="regression fixture",
                steps=(
                    WorkflowStepSpec(step_key="preflight", handler_key="test.preflight_est"),
                    WorkflowStepSpec(step_key="train", handler_key="test.train_est", depends_on=("preflight",)),
                ),
            )
        )
        run = self.orch.trigger_workflow("test.prior_output_budget")
        steps = {s["step_key"]: s for s in run["steps"]}
        self.assertEqual(steps["preflight"]["status"], "COMPLETED")
        self.assertEqual(steps["train"]["status"], "BLOCKED")
        self.assertIn("parameter_budget_exceeded", run["error_message"])
        self.assertEqual(calls, [])

    def test_payload_budget_still_enforced(self) -> None:
        calls: list[dict[str, Any]] = []
        self.orch.registry.register_handler("test.payload_handler", _recording_handler(calls))
        self.orch.registry.register_definition(
            _single_step_definition("test.payload_budget", "test.payload_handler")
        )
        run = self.orch.trigger_workflow("test.payload_budget", payload={"estimated_params": OVER_CAP})
        self.assertEqual(run["status"], "BLOCKED")
        self.assertEqual(calls, [])

    def test_invalid_type_fails_closed(self) -> None:
        for index, bad_value in enumerate(("not-a-number", True, -1, 2.5, {"nested": 1})):
            with self.subTest(bad_value=bad_value):
                calls: list[dict[str, Any]] = []
                key = f"test.invalid_budget_{index}"
                handler_key = f"{key}.handler"
                self.orch.registry.register_handler(handler_key, _recording_handler(calls))
                self.orch.registry.register_definition(
                    _single_step_definition(key, handler_key, estimated_params=bad_value)
                )
                run = self.orch.trigger_workflow(key)
                self.assertEqual(run["status"], "BLOCKED")
                self.assertIn("invalid_estimated_params", run["error_message"])
                self.assertEqual(calls, [])

    def test_spec_from_dict_validates_budget(self) -> None:
        spec = WorkflowStepSpec.from_dict({"step_key": "s", "handler_key": "h", "estimated_params": 1234})
        self.assertEqual(spec.estimated_params, 1234)
        self.assertIsNone(WorkflowStepSpec.from_dict({"step_key": "s", "handler_key": "h"}).estimated_params)
        for bad_value in ("abc", True, -5, 1.5):
            with self.subTest(bad_value=bad_value):
                with self.assertRaises(WorkflowValidationError):
                    WorkflowStepSpec.from_dict(
                        {"step_key": "s", "handler_key": "h", "estimated_params": bad_value}
                    )


class TestResolverAndGuardUnits(unittest.TestCase):
    def test_resolver_prefers_config_then_declared_dependency(self) -> None:
        configured = WorkflowStepSpec(step_key="s", handler_key="h", estimated_params=42)
        self.assertEqual(resolve_estimated_params(configured, {"prev": {"estimated_params": 7}}), 42)
        dependent = WorkflowStepSpec(step_key="s", handler_key="h", depends_on=("a", "b"))
        outputs = {"b": {"estimated_params": 20}, "a": {"estimated_params": 10}}
        self.assertEqual(resolve_estimated_params(dependent, outputs), 10)
        self.assertIsNone(resolve_estimated_params(WorkflowStepSpec(step_key="s", handler_key="h"), None))

    def test_guard_rejects_invalid_and_over_cap_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            guard = WorkflowResourceGuard(work_dir=tmp)
            step = WorkflowStepSpec(step_key="s", handler_key="h")
            self.assertTrue(guard.check_step(step, {"estimated_params": OVER_CAP}, estimated_params=10).allowed)
            over = guard.check_step(step, {}, estimated_params=OVER_CAP)
            self.assertEqual((over.allowed, over.reason), (False, "parameter_budget_exceeded"))
            at_cap = guard.check_step(step, {}, estimated_params=MAX_CPU_MODEL_PARAMETERS)
            self.assertTrue(at_cap.allowed)
            for bad_value in ("lots", True, -3, 4.5, [1, 2]):
                with self.subTest(bad_value=bad_value):
                    out = guard.check_step(step, {"estimated_params": bad_value})
                    self.assertEqual((out.allowed, out.blocked, out.reason), (False, True, "invalid_estimated_params"))


if __name__ == "__main__":
    unittest.main()
