"""Runtime unit & integration tests for the Central Native Workflow Engine & Model Registry Lifecycle.

Pure Python standard-library test suite (unittest) verifying real execution,
SQLite persistence, DAG validation, 2-tier HMAC approval gates, recovery rules,
resource caps, audit redaction, and ModelRegistry evaluation-gated lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from apps.core.native.registry import ModelRegistry, RegistryError
from apps.core.native.tokenizer import ZyrquenTokenizer
from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager
from apps.core.workflow import (
    ApprovalViolationError,
    CentralWorkflowOrchestrator,
    LeakageGateFailedError,
    NaNInfWorkflowError,
    OutOfMemoryWorkflowError,
    StepExecutionResult,
    WorkflowDefinition,
    WorkflowStepSpec,
    WorkflowValidationError,
    validate_dag,
)
from apps.core.workflow.audit import redact_dict


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_save(obj: object, path: str) -> None:
    Path(path).write_text(json.dumps(obj), encoding="utf-8")


def _json_load(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class TestWorkflowDAGAndRegistry(unittest.TestCase):
    def test_validate_dag_topological_order_and_rejections(self) -> None:
        steps = (
            WorkflowStepSpec(step_key="a", handler_key="h.a"),
            WorkflowStepSpec(step_key="b", handler_key="h.b", depends_on=("a",)),
            WorkflowStepSpec(step_key="c", handler_key="h.c", depends_on=("a", "b")),
        )
        self.assertEqual(validate_dag(steps), ["a", "b", "c"])

        # Cycle rejected
        cyclic = (
            WorkflowStepSpec(step_key="a", handler_key="h.a", depends_on=("b",)),
            WorkflowStepSpec(step_key="b", handler_key="h.b", depends_on=("a",)),
        )
        with self.assertRaises(WorkflowValidationError):
            validate_dag(cyclic)

        # Missing dependency rejected
        missing_dep = (WorkflowStepSpec(step_key="a", handler_key="h.a", depends_on=("ghost",)),)
        with self.assertRaises(WorkflowValidationError):
            validate_dag(missing_dep)

        # Duplicate step key rejected
        dup = (
            WorkflowStepSpec(step_key="a", handler_key="h.a"),
            WorkflowStepSpec(step_key="a", handler_key="h.a"),
        )
        with self.assertRaises(WorkflowValidationError):
            validate_dag(dup)

        # Invalid lane rejected
        with self.assertRaises(WorkflowValidationError):
            validate_dag((WorkflowStepSpec(step_key="a", handler_key="h.a", lane="bad_lane"),))

    def test_all_eight_workflow_groups_registered_and_single_scheduler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = CentralWorkflowOrchestrator(
                db_path=Path(tmp) / "wf.db",
                work_dir=tmp,
                approval_secret="test-approval-secret-32-chars-minimum!",
            )
            defs = orch.registry.list_definitions()
            groups = {d.group_name for d in defs}
            self.assertEqual(
                groups,
                {
                    "system_ops",
                    "data",
                    "training",
                    "evaluation",
                    "knowledge_memory",
                    "improvement_proposal",
                    "security_governance",
                    "project_dev",
                },
            )
            self.assertGreaterEqual(len(defs), 9)
            self.assertIn("project_dev.autonomous_maintainer", {d.workflow_key for d in defs})
            self.assertFalse(orch.scheduler.is_running())


class TestWorkflowExecutionAndGovernance(unittest.TestCase):
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

    def test_tier1_builtin_workflows_honest_execution(self) -> None:
        # 1. System ops passes with real resource snapshot
        sys_run = self.orch.trigger_workflow("system_ops.health_check", dedup_key="sys-1")
        self.assertEqual(sys_run["status"], "COMPLETED")
        steps_by_key = {s["step_key"]: s for s in sys_run["steps"]}
        self.assertEqual(steps_by_key["check_health"]["evidence"]["verdict"], "PASS")
        self.assertEqual(steps_by_key["daily_report"]["evidence"]["verdict"], "PASS")
        self.assertIn("ram_mb", steps_by_key["check_health"]["output"]["resource_snapshot"])

        # Idempotent dedup returns existing run
        dup_run = self.orch.trigger_workflow("system_ops.health_check", dedup_key="sys-1")
        self.assertEqual(dup_run["id"], sys_run["id"])

        # 2. Data audit without dataset returns NOT RUN honestly (never fabricated PASS)
        data_run = self.orch.trigger_workflow("data.ingestion_and_leakage_gate")
        self.assertEqual(data_run["status"], "BLOCKED")
        self.assertEqual(data_run["steps"][0]["evidence"]["verdict"], "NOT RUN")

        # 3. Knowledge ingestion checks tenant isolation & scrubs PII
        kn_run = self.orch.trigger_workflow(
            "knowledge.memory_ingestion",
            payload={"owner_id": "u1", "workspace_id": "ws1", "content": "Contact me at test@example.com"},
        )
        self.assertEqual(kn_run["status"], "COMPLETED")
        self.assertTrue(kn_run["steps"][0]["output"]["pii_redacted"])

        # 4. Security & project_dev workflows complete cleanly
        sec_run = self.orch.trigger_workflow("security.integrity_audit")
        self.assertEqual(sec_run["status"], "COMPLETED")
        proj_run = self.orch.trigger_workflow("project_dev.roadmap_sync")
        self.assertEqual(proj_run["status"], "COMPLETED")
        self.assertTrue(proj_run["steps"][0]["output"]["push_or_deploy_blocked_without_approval"])

    def test_tier2_hmac_approval_rbac_tamper_and_single_use(self) -> None:
        # Register a pure-stdlib Tier-2 custom workflow to test end-to-end resume + COMPLETED
        self.orch.registry.register_handler(
            "test.tier2_op",
            lambda ctx, payload: StepExecutionResult(
                verdict="PASS",
                summary="Tier-2 verified execution",
                output={"consumed_approval_id": (ctx.get("consumed_approval") or {}).get("id")},
                evidence={"verdict": "PASS"},
            ),
        )
        self.orch.registry.register_definition(
            WorkflowDefinition(
                workflow_key="test.tier2_custom",
                version="1.0.0",
                group_name="training",
                title="Custom Tier-2 Gate Test",
                description="Tests HMAC approval gate",
                default_tier="tier2_approval",
                steps=(
                    WorkflowStepSpec(
                        step_key="gated_step",
                        handler_key="test.tier2_op",
                        description="Requires Tier-2 admin signature",
                        lane="control_ops",
                        tier="tier2_approval",
                        action_type="model.promote",
                    ),
                ),
            )
        )

        run = self.orch.trigger_workflow("test.tier2_custom", requested_by_user_id="user-42")
        self.assertEqual(run["status"], "WAITING_APPROVAL")
        self.assertEqual(len(run["approvals"]), 1)
        approval_id = run["approvals"][0]["id"]

        # Non-admin must be rejected
        with self.assertRaises(ApprovalViolationError):
            self.orch.decide_approval_and_resume(
                approval_id,
                approve=True,
                approver_user_id="user-42",
                approver_role="user",
            )

        # Admin approves -> HMAC generated -> step executes -> token consumed -> COMPLETED
        resumed = self.orch.decide_approval_and_resume(
            approval_id,
            approve=True,
            approver_user_id="admin-1",
            approver_role="admin",
            reason="Verified safety gate",
        )
        self.assertEqual(resumed["status"], "COMPLETED")
        self.assertEqual(resumed["steps"][0]["output"]["consumed_approval_id"], approval_id)
        consumed_rec = self.orch.store.get_approval(approval_id)
        self.assertEqual(consumed_rec["status"], "consumed")
        self.assertIsNotNone(consumed_rec["consumed_at"])

        # Replay decision on consumed approval must fail
        with self.assertRaises(ApprovalViolationError):
            self.orch.decide_approval_and_resume(
                approval_id,
                approve=True,
                approver_user_id="admin-1",
                approver_role="admin",
            )

    def test_hmac_tamper_blocks_execution(self) -> None:
        self.orch.registry.register_handler(
            "test.tier2_tamper",
            lambda ctx, payload: StepExecutionResult(verdict="PASS", summary="Should not run"),
        )
        self.orch.registry.register_definition(
            WorkflowDefinition(
                workflow_key="test.tamper_gate",
                version="1.0.0",
                group_name="training",
                title="Tamper Test",
                description="Detect tampered HMAC",
                default_tier="tier2_approval",
                steps=(
                    WorkflowStepSpec(
                        step_key="gated",
                        handler_key="test.tier2_tamper",
                        description="Needs admin approval",
                        tier="tier2_approval",
                        action_type="training.execute",
                    ),
                ),
            )
        )
        run = self.orch.trigger_workflow("test.tamper_gate")
        app_id = run["approvals"][0]["id"]
        # Forge an approved status with invalid HMAC directly in DB
        self.orch.store.set_approval_decision(
            app_id,
            status="approved",
            approved_by_user_id="attacker",
            signature_hmac="0" * 64,
        )
        # Try to execute step directly -> Governance HMAC check must block it
        self.orch.store.update_step(run["id"], "gated", status="PENDING")
        self.orch.store.update_run(run["id"], status="PENDING")
        blocked_run = self.orch.execute_run(run["id"])
        self.assertEqual(blocked_run["status"], "BLOCKED")
        self.assertIn("HMAC", blocked_run["error_message"])

    def test_training_workflow_pauses_then_blocks_honestly_without_torch(self) -> None:
        ds_dir = self.tmp_dir / "dataset_dummy"
        ds_dir.mkdir()
        run = self.orch.trigger_workflow(
            "training.native_controlled_run",
            payload={"dataset_dir": str(ds_dir)},
        )
        self.assertEqual(run["status"], "WAITING_APPROVAL")
        steps = {s["step_key"]: s for s in run["steps"]}
        self.assertEqual(steps["preflight"]["status"], "COMPLETED")
        self.assertEqual(steps["execute_training"]["status"], "WAITING_APPROVAL")

        # Admin approves -> handler runs and checks torch -> BLOCKED honestly (no torch installed here)
        app_id = run["approvals"][0]["id"]
        after = self.orch.decide_approval_and_resume(
            app_id,
            approve=True,
            approver_user_id="admin-1",
            approver_role="admin",
        )
        self.assertEqual(after["status"], "BLOCKED")
        after_steps = {s["step_key"]: s for s in after["steps"]}
        self.assertIn(after_steps["execute_training"]["error_code"], ("torch_not_installed", "training_hook_not_implemented", "tokenizer_missing"))

    def test_resource_guard_blocks_unapproved_paid_gpu_and_cpu_overflow(self) -> None:
        # Unapproved paid GPU step is blocked immediately before handler runs
        self.orch.registry.register_handler(
            "test.paid_gpu_handler",
            lambda ctx, payload: StepExecutionResult(verdict="PASS", summary="Should be blocked"),
        )
        self.orch.registry.register_definition(
            WorkflowDefinition(
                workflow_key="test.paid_gpu",
                version="1.0.0",
                group_name="training",
                title="Paid GPU",
                description="Tests paid GPU block",
                default_tier="tier2_approval",
                steps=(
                    WorkflowStepSpec(
                        step_key="gpu_step",
                        handler_key="test.paid_gpu_handler",
                        description="Paid GPU step",
                        lane="compute_heavy",
                        requires_paid_gpu=True,
                    ),
                ),
            )
        )
        blocked_gpu = self.orch.trigger_workflow("test.paid_gpu")
        self.assertEqual(blocked_gpu["status"], "BLOCKED")
        self.assertIn("Paid cloud GPU compute is blocked", blocked_gpu["error_message"])

        # CPU overflow params > 5M blocked
        overflow = self.orch.trigger_workflow(
            "training.native_controlled_run",
            payload={"dataset_dir": str(self.tmp_dir), "estimated_params": 10_000_000},
        )
        # preflight completes, execute_training lane=compute_heavy hits CPU cap block before Tier-2
        steps = {s["step_key"]: s for s in overflow["steps"]}
        self.assertEqual(steps["execute_training"]["status"], "BLOCKED")
        self.assertEqual(steps["execute_training"]["error_code"], "resource_blocked")

    def test_non_retryable_errors_and_transient_retry_recovery(self) -> None:
        attempts = {"count": 0}

        def flaky_handler(ctx: dict, payload: dict) -> StepExecutionResult:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("transient connection reset")
            return StepExecutionResult(verdict="PASS", summary="Recovered on attempt 2")

        self.orch.registry.register_handler("test.flaky", flaky_handler)
        self.orch.registry.register_definition(
            WorkflowDefinition(
                workflow_key="test.retryable",
                version="1.0.0",
                group_name="system_ops",
                title="Retryable Test",
                description="Transient retry succeeds on second attempt",
                steps=(
                    WorkflowStepSpec(
                        step_key="flaky",
                        handler_key="test.flaky",
                        description="Flaky step",
                        max_attempts=2,
                        retry_backoff_sec=0.01,
                    ),
                ),
            )
        )
        recovered_run = self.orch.trigger_workflow("test.retryable")
        self.assertEqual(recovered_run["status"], "COMPLETED")
        self.assertEqual(recovered_run["steps"][0]["attempt"], 2)

        # Non-retryable NaN / Leakage / OOM must stop after 1 attempt even if max_attempts=3
        oom_attempts = {"count": 0}

        def oom_handler(ctx: dict, payload: dict) -> StepExecutionResult:
            oom_attempts["count"] += 1
            raise OutOfMemoryWorkflowError("CUDA out of memory")

        self.orch.registry.register_handler("test.oom", oom_handler)
        self.orch.registry.register_definition(
            WorkflowDefinition(
                workflow_key="test.oom_wf",
                version="1.0.0",
                group_name="training",
                title="OOM Abort Test",
                description="Abort immediately on OOM",
                steps=(
                    WorkflowStepSpec(
                        step_key="oom",
                        handler_key="test.oom",
                        description="Fails with OOM",
                        max_attempts=3,
                    ),
                ),
            )
        )
        oom_run = self.orch.trigger_workflow("test.oom_wf")
        self.assertEqual(oom_run["status"], "FAILED")
        self.assertEqual(oom_attempts["count"], 1)
        self.assertEqual(oom_run["steps"][0]["error_code"], "out_of_memory")

        # Classification check for NaN and LeakageGateFailedError
        self.assertEqual(
            self.orch.recovery.classify_exception(NaNInfWorkflowError("nan loss")),
            (False, "nan_inf_loss", "FAILED"),
        )
        self.assertEqual(
            self.orch.recovery.classify_exception(LeakageGateFailedError("leakage")),
            (False, "leakage_gate_failed", "BLOCKED"),
        )

    def test_orphan_reconciliation_and_scheduler_and_redaction(self) -> None:
        # Simulate orphaned RUNNING run left over from crash
        orphan, _ = self.orch.store.create_run(
            workflow_key="system_ops.health_check",
            workflow_version="1.0.0",
            trigger_type="manual",
            trigger_payload={},
            steps=[
                {"step_key": "check_health", "depends_on": [], "lane": "control_ops", "max_attempts": 2},
                {"step_key": "daily_report", "depends_on": ["check_health"], "lane": "control_ops", "max_attempts": 2},
            ],
        )
        self.orch.store.update_run(orphan["id"], status="RUNNING")
        self.orch.store.update_step(orphan["id"], "check_health", status="RUNNING", attempt=1)

        requeued = self.orch.recovery.reconcile_orphaned_runs(self.orch.queue)
        self.assertIn(orphan["id"], requeued)
        reloaded = self.orch.store.get_run(orphan["id"])
        self.assertEqual(reloaded["status"], "PENDING")
        steps = {s["step_key"]: s for s in reloaded["steps"]}
        self.assertEqual(steps["check_health"]["status"], "PENDING")

        # Audit secret redaction check
        sanitized = redact_dict(
            {
                "Authorization": "Bearer supersecretvalue123",
                "signature_hmac": "deadbeef" * 8,
                "nested": {"api_key": "sk-1234567890", "safe": "ok"},
            }
        )
        self.assertEqual(sanitized["Authorization"], "[REDACTED]")
        self.assertEqual(sanitized["signature_hmac"], "[REDACTED]")
        self.assertEqual(sanitized["nested"]["api_key"], "[REDACTED]")
        self.assertEqual(sanitized["nested"]["safe"], "ok")

        # Single CentralScheduler tick dispatches due workflows once per slot
        due = self.orch.scheduler.run_due_schedules(now=datetime.now(timezone.utc))
        self.assertGreaterEqual(len(due), 2)
        due_again = self.orch.scheduler.run_due_schedules(now=datetime.now(timezone.utc))
        self.assertEqual(due_again, [])


class TestModelRegistryLifecycleAndEvaluationGate(unittest.TestCase):
    def _create_dummy_artifacts(self, root: Path, dataset_version: str = "ds-v1") -> tuple[Path, Path, Path]:
        tok_path = root / "tokenizer.json"
        tok = ZyrquenTokenizer.train(["alpha beta gamma alpha beta", "delta epsilon alpha"], vocab_size=260)
        tok.save(tok_path)

        ds_dir = root / "dataset"
        ds_dir.mkdir(parents=True, exist_ok=True)
        files_meta = {}
        combined_parts = []
        for split in ("train", "validation", "test"):
            p = ds_dir / f"{split}.jsonl"
            content = json.dumps({"input": split, "target": "ok"}).encode("utf-8") + b"\n"
            p.write_bytes(content)
            sha = _sha256_bytes(content)
            files_meta[f"{split}.jsonl"] = {"sha256": sha}
            combined_parts.append(sha)
        manifest = {
            "version": dataset_version,
            "files": files_meta,
            "content_sha256": hashlib.sha256("".join(combined_parts).encode()).hexdigest(),
        }
        (ds_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        ckpt_dir = root / "checkpoints"
        cm = CheckpointManager(ckpt_dir, save_fn=_json_save, load_fn=_json_load)
        cm.save(
            100,
            {
                "step": 100,
                "tokenizer_sha256": tok.fingerprint(),
                "dataset_version": dataset_version,
                "config": {"lr": 1e-3},
                "model_config": {"d_model": 128},
            },
        )
        return ckpt_dir, tok_path, ds_dir

    def test_evaluation_gate_quarantine_verify_promote_compare_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ckpt_dir, tok_path, ds_dir = self._create_dummy_artifacts(root)
            registry = ModelRegistry(root / "registry", load_fn=_json_load)

            rec1 = registry.register_next_native_version(
                ckpt_dir,
                tok_path,
                ds_dir,
                metrics={"test_unseen_fg_exact": 0.65, "test_ood_fg_exact": 0.50},
                notes="Baseline v0.1.0",
            )
            v1 = rec1["version"]
            self.assertEqual(v1, "ZYRQUEN-Native-0.1.0")
            self.assertEqual(rec1["lifecycle_status"], "registered")

            # Cannot promote before evaluation evidence when evaluation gate enforced
            with self.assertRaises(RegistryError):
                registry.promote(v1, enforce_evaluation_gate=True, approval_id="app-1")

            # Attach failing evaluation -> transitions to quarantined & blocks promote
            registry.attach_evaluation_evidence(
                v1,
                eval_run_id="eval-fail-1",
                report_sha256="a" * 64,
                metrics={"test_unseen_fg_exact": 0.65},
                passed=False,
                zero_regression=True,
                reason="below threshold",
            )
            self.assertEqual(registry.get(v1)["lifecycle_status"], "quarantined")
            with self.assertRaises(RegistryError):
                registry.promote(v1, enforce_evaluation_gate=True, approval_id="app-1")

            # Attach passing evaluation -> verified -> staged -> promoted -> production
            registry.attach_evaluation_evidence(
                v1,
                eval_run_id="eval-pass-1",
                report_sha256="b" * 64,
                metrics={"test_unseen_fg_exact": 0.85, "test_ood_fg_exact": 0.72},
                passed=True,
                zero_regression=True,
            )
            self.assertEqual(registry.get(v1)["lifecycle_status"], "verified")
            registry.set_lifecycle_status(v1, "staging", approval_id="app-stage", approved_by="admin@local")
            self.assertEqual(registry.get(v1)["lifecycle_status"], "staging")

            # Approval ID is mandatory for gated promote
            with self.assertRaises(RegistryError):
                registry.promote(v1, enforce_evaluation_gate=True, approval_id=None)

            registry.promote(
                v1,
                enforce_evaluation_gate=True,
                approval_id="app-prod-1",
                approved_by="admin@local",
            )
            self.assertEqual(registry.active_version(), v1)
            self.assertEqual(registry.get(v1)["lifecycle_status"], "production")

            # Register v2 with parent v1, compare versions, promote v2, then rollback to v1
            rec2 = registry.register_next_native_version(
                ckpt_dir,
                tok_path,
                ds_dir,
                metrics={"test_unseen_fg_exact": 0.90, "test_ood_fg_exact": 0.78},
            )
            v2 = rec2["version"]
            self.assertEqual(rec2["parent"], v1)
            cmp = registry.compare_versions(v1, v2)
            self.assertTrue(cmp["zero_regression"])
            self.assertEqual(cmp["regressed_metrics"], [])
            self.assertGreater(cmp["metric_deltas"]["test_unseen_fg_exact"]["delta"], 0)

            registry.attach_evaluation_evidence(
                v2,
                eval_run_id="eval-pass-2",
                report_sha256="c" * 64,
                metrics={"test_unseen_fg_exact": 0.90, "test_ood_fg_exact": 0.78},
                passed=True,
                zero_regression=True,
            )
            registry.promote(v2, enforce_evaluation_gate=True, approval_id="app-prod-2", approved_by="admin@local")
            self.assertEqual(registry.active_version(), v2)
            self.assertEqual(registry.get(v1)["lifecycle_status"], "archived")

            rolled = registry.rollback(approval_id="app-rb-1")
            self.assertEqual(rolled, v1)
            self.assertEqual(registry.active_version(), v1)
            self.assertEqual(registry.get(v1)["lifecycle_status"], "production")

            # Compatibility & Lineage verification
            compat = registry.check_compatibility(v2)
            self.assertTrue(compat["compatible"])
            self.assertTrue(compat["checks"]["artifacts_sha256"])
            self.assertTrue(compat["checks"]["tokenizer_sha256"])
            self.assertTrue(compat["checks"]["architecture_config"])

            lineage = registry.get_lineage(v2)
            self.assertEqual(lineage["depth"], 2)
            self.assertEqual([a["version"] for a in lineage["ancestors"]], [v2, v1])

            # Capability regression detection
            registry.attach_evaluation_evidence(
                v1,
                eval_run_id="eval-cap-1",
                report_sha256="d" * 64,
                metrics={"test_unseen_fg_exact": 0.85},
                capabilities={"relational_reasoning": 0.82},
                passed=True,
                zero_regression=True,
            )
            registry.attach_evaluation_evidence(
                v2,
                eval_run_id="eval-cap-2",
                report_sha256="e" * 64,
                metrics={"test_unseen_fg_exact": 0.90},
                capabilities={"relational_reasoning": 0.70},
                passed=True,
                zero_regression=True,
            )
            cap_cmp = registry.compare_versions(v1, v2)
            self.assertFalse(cap_cmp["zero_regression"])
            self.assertIn("relational_reasoning", cap_cmp["regressed_capabilities"])

            # Frozen baseline names v7/v8 cannot be overwritten
            with self.assertRaises(RegistryError):
                registry.register("v8", ckpt_dir, tok_path, ds_dir)

            # Blocked/failed states cannot be promoted
            registry.set_lifecycle_status(v2, "blocked", reason="manual block")
            with self.assertRaises(RegistryError):
                registry.promote(v2, enforce_evaluation_gate=True, approval_id="app-blocked")

    def test_startup_recovery_respects_zyrquen_workflow_recovery_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "wf_recovery.db"
            orch = CentralWorkflowOrchestrator(
                db_path=db_path,
                work_dir=tmp,
                approval_secret="unit-test-secret-key-at-least-32-bytes",
            )
            run, created = orch.store.create_run(
                workflow_key="system_ops.health_check",
                workflow_version="1.0.0",
                trigger_type="manual",
                trigger_payload={},
                steps=[{"step_key": "check_health", "handler_key": "system_ops.check_health", "status": "RUNNING", "attempt": 1, "max_attempts": 2}],
                requested_by_user_id="user-1",
            )
            self.assertTrue(created)
            orch.store.update_run(run["id"], status="RUNNING")
            orch.shutdown(wait=True)

            # With ZYRQUEN_WORKFLOW_RECOVERY=0, start() must not reconcile or requeue orphaned runs
            prev = os.environ.get("ZYRQUEN_WORKFLOW_RECOVERY")
            os.environ["ZYRQUEN_WORKFLOW_RECOVERY"] = "0"
            try:
                orch_guarded = CentralWorkflowOrchestrator(
                    db_path=db_path,
                    work_dir=tmp,
                    approval_secret="unit-test-secret-key-at-least-32-bytes",
                )
                recovered_disabled = orch_guarded.start(enable_scheduler=False)
                self.assertEqual(recovered_disabled, [])
                persisted = orch_guarded.store.get_run(run["id"])
                self.assertIsNotNone(persisted)
                self.assertEqual(persisted["status"], "RUNNING")
                orch_guarded.shutdown(wait=True)
            finally:
                if prev is None:
                    os.environ.pop("ZYRQUEN_WORKFLOW_RECOVERY", None)
                else:
                    os.environ["ZYRQUEN_WORKFLOW_RECOVERY"] = prev

            # With recovery enabled (default), orphaned RUNNING run is reconciled
            orch_default = CentralWorkflowOrchestrator(
                db_path=db_path,
                work_dir=tmp,
                approval_secret="unit-test-secret-key-at-least-32-bytes",
            )
            recovered_enabled = orch_default.start(enable_scheduler=False)
            self.assertEqual(recovered_enabled, [run["id"]])
            status_enabled = orch_default.get_service_status()
            self.assertTrue(status_enabled["started"])
            self.assertTrue(status_enabled["scheduler"]["safely_disabled"])
            self.assertFalse(status_enabled["scheduler"]["running"])
            self.assertTrue(status_enabled["recovery"]["enabled"])
            self.assertFalse(status_enabled["recovery"]["safely_disabled"])
            self.assertTrue(status_enabled["recovery"]["startup_reconciliation_ran"])
            self.assertEqual(status_enabled["recovery"]["reconciled_runs_count"], 1)
            self.assertFalse(status_enabled["diagnostics_safe_mode"])
            orch_default.shutdown(wait=True)

    def test_get_service_status_reflects_disabled_diagnostics_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prev_sched = os.environ.get("ZYRQUEN_WORKFLOW_SCHEDULER")
            prev_rec = os.environ.get("ZYRQUEN_WORKFLOW_RECOVERY")
            os.environ["ZYRQUEN_WORKFLOW_SCHEDULER"] = "0"
            os.environ["ZYRQUEN_WORKFLOW_RECOVERY"] = "0"
            try:
                orch = CentralWorkflowOrchestrator(
                    db_path=Path(tmp) / "wf_diag.db",
                    work_dir=tmp,
                    approval_secret="unit-test-secret-key-at-least-32-bytes",
                )
                recovered = orch.start(enable_scheduler=False, enable_recovery=False)
                self.assertEqual(recovered, [])
                status = orch.get_service_status()
                self.assertEqual(status["service"], "zyrquen-workflow-engine")
                self.assertTrue(status["started"])
                self.assertTrue(status["diagnostics_safe_mode"])
                self.assertEqual(status["scheduler"]["status"], "disabled")
                self.assertFalse(status["scheduler"]["enabled"])
                self.assertFalse(status["scheduler"]["running"])
                self.assertTrue(status["scheduler"]["safely_disabled"])
                self.assertFalse(status["scheduler"]["env_enabled"])
                self.assertEqual(status["recovery"]["status"], "disabled")
                self.assertFalse(status["recovery"]["enabled"])
                self.assertTrue(status["recovery"]["safely_disabled"])
                self.assertFalse(status["recovery"]["env_enabled"])
                self.assertFalse(status["recovery"]["startup_reconciliation_ran"])
                self.assertEqual(status["recovery"]["reconciled_runs_count"], 0)
                orch.shutdown(wait=True)
            finally:
                if prev_sched is None:
                    os.environ.pop("ZYRQUEN_WORKFLOW_SCHEDULER", None)
                else:
                    os.environ["ZYRQUEN_WORKFLOW_SCHEDULER"] = prev_sched
                if prev_rec is None:
                    os.environ.pop("ZYRQUEN_WORKFLOW_RECOVERY", None)
                else:
                    os.environ["ZYRQUEN_WORKFLOW_RECOVERY"] = prev_rec


if __name__ == "__main__":
    unittest.main()
