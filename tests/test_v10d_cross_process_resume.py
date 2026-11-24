"""V10-D cross-process approval and workflow-resume runtime test.

Uses a synthetic handler only: it proves process-boundary orchestration and
single-use governance without invoking model training or changing model state.
"""
from __future__ import annotations

import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path

from apps.core.workflow.models import (
    StepExecutionResult,
    WorkflowDefinition,
    WorkflowStepSpec,
)
from apps.core.workflow.orchestrator import CentralWorkflowOrchestrator

SECRET = "v10d-cross-process-test-secret"
WORKFLOW_KEY = "test.v10d_cross_process_resume"
VERSION = "1.0.0"
STEP_KEY = "execute_gated_test_step"
HANDLER_KEY = "test.gated_handler"


def _definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow_key=WORKFLOW_KEY,
        version=VERSION,
        group_name="training",
        title="Cross-process approval resume test",
        description="Synthetic no-training test for shared workflow persistence.",
        default_tier="tier2_approval",
        steps=(
            WorkflowStepSpec(
                step_key=STEP_KEY,
                handler_key=HANDLER_KEY,
                description="Synthetic gated step; never trains a model",
                lane="compute_heavy",
                tier="tier2_approval",
                action_type="training.execute",
                max_attempts=1,
                min_disk_gb=0.01,
                estimated_ram_mb=1,
            ),
        ),
    )


def _api_process_approve_and_resume(db_path: str, work_dir: str, approval_id: str, result_queue) -> None:
    """Simulate the API worker orchestration after its auth layer accepts an admin."""
    os.environ["ZYRQUEN_APPROVAL_SECRET"] = SECRET
    engine = CentralWorkflowOrchestrator(
        db_path=db_path,
        work_dir=work_dir,
        approval_secret=SECRET,
    )
    try:
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
                summary="Synthetic handler completed; model training was not invoked.",
                output={"synthetic_only": True, "training_invoked": False},
            )

        engine.registry.register_handler(HANDLER_KEY, synthetic_handler)
        run = engine.decide_approval_and_resume(
            approval_id,
            approve=True,
            approver_user_id="test-authenticated-admin-id",
            approver_role="admin",
            reason="Cross-process test approval",
            execute_async=False,
        )
        result_queue.put({"status": "ok", "run_id": run["id"], "run_status": run["status"]})
    except Exception as exc:  # return child-process failures to the parent test
        result_queue.put({"status": "error", "error": repr(exc)})
    finally:
        engine.shutdown(wait=True)


class TestV10DCrossProcessResume(unittest.TestCase):
    def test_api_process_approves_and_resumes_runner_created_workflow(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "shared-v10d-workflow.db")
            work_dir = str(Path(td))
            os.environ["ZYRQUEN_APPROVAL_SECRET"] = SECRET

            runner = CentralWorkflowOrchestrator(
                db_path=db_path,
                work_dir=work_dir,
                approval_secret=SECRET,
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
                    version=VERSION,
                    trigger_type="manual",
                    payload={"test_only": True},
                    requested_by_user_id="test-requester",
                    actor_id="test-requester",
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
                target=_api_process_approve_and_resume,
                args=(db_path, work_dir, approval_id, result_queue),
            )
            api_process.start()
            api_process.join(timeout=30)
            if api_process.is_alive():
                api_process.terminate()
                api_process.join()
                self.fail("API worker process timed out while resuming the workflow")
            self.assertEqual(api_process.exitcode, 0)

            child_result = result_queue.get(timeout=5)
            self.assertEqual(child_result.get("status"), "ok", child_result)
            self.assertEqual(child_result.get("run_id"), run_id)
            self.assertEqual(child_result.get("run_status"), "COMPLETED")

            verifier = CentralWorkflowOrchestrator(
                db_path=db_path,
                work_dir=work_dir,
                approval_secret=SECRET,
            )
            try:
                final_run = verifier.store.get_run(run_id)
                final_approval = verifier.store.get_approval(approval_id)
                self.assertEqual(final_run["status"], "COMPLETED")
                self.assertEqual(final_approval["status"], "consumed")
                step = next(item for item in final_run["steps"] if item["step_key"] == STEP_KEY)
                self.assertEqual(step["output"]["synthetic_only"], True)
                self.assertEqual(step["output"]["training_invoked"], False)
            finally:
                verifier.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
