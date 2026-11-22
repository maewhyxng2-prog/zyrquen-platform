"""Central Native Workflow Orchestrator uniting DAG, ResourceGuard, Governance, Queue, Recovery, Audit, and Triggers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from apps.core.workflow.audit import WorkflowAuditLogger, redact_text
from apps.core.workflow.dag import resolve_ready_steps
from apps.core.workflow.governance import WorkflowGovernance
from apps.core.workflow.handlers import register_builtin_workflows
from apps.core.workflow.models import (
    ApprovalViolationError,
    StepExecutionResult,
    WorkflowDefinition,
    WorkflowStepSpec,
    utc_now_iso,
)
from apps.core.workflow.queue import DualLaneTaskQueue
from apps.core.workflow.recovery import RecoveryManager
from apps.core.workflow.registry import WorkflowRegistry
from apps.core.workflow.resource_guard import WorkflowResourceGuard
from apps.core.workflow.store import WorkflowStore
from apps.core.workflow.triggers import CentralScheduler, EventBus


class CentralWorkflowOrchestrator:
    def __init__(
        self,
        *,
        db_path: str | Path = "/tmp/zyrquen_workflow.db",
        work_dir: str | Path = ".",
        approval_secret: str | None = None,
        scheduler_interval_sec: float = 60.0,
    ) -> None:
        self.store = WorkflowStore(db_path)
        self.registry = WorkflowRegistry()
        self.audit = WorkflowAuditLogger(self.store)
        self.resource_guard = WorkflowResourceGuard(work_dir=work_dir)
        self.governance = WorkflowGovernance(self.store, secret=approval_secret)
        self.queue = DualLaneTaskQueue(control_workers=2, compute_workers=1)
        self.recovery = RecoveryManager(self.store, self.audit)
        self.event_bus = EventBus(self)
        self.scheduler = CentralScheduler(self, poll_interval_sec=scheduler_interval_sec)

        for defn in register_builtin_workflows(self.registry):
            self.store.upsert_definition(
                defn.workflow_key,
                defn.version,
                defn.group_name,
                defn.to_dag_spec(),
                defn.default_tier,
                defn.is_active,
            )

    def start(self, *, enable_scheduler: bool = True) -> list[str]:
        recovered = self.recovery.reconcile_orphaned_runs(self.queue)
        for run_id in recovered:
            run = self.store.get_run(run_id)
            if run and run["status"] == "PENDING":
                self._schedule_run_execution(run_id)
        if enable_scheduler:
            self.scheduler.start()
        return recovered

    def shutdown(self, wait: bool = True) -> None:
        self.scheduler.stop()
        self.queue.shutdown(wait=wait)

    def trigger_workflow(
        self,
        workflow_key: str,
        *,
        version: str | None = None,
        trigger_type: str = "manual",
        payload: dict[str, Any] | None = None,
        requested_by_user_id: str | None = None,
        actor_id: str | None = None,
        dedup_key: str | None = None,
        priority: int = 50,
        execute_async: bool = False,
    ) -> dict[str, Any]:
        defn = self.registry.get(workflow_key, version)
        run, created = self.store.create_run(
            workflow_key=defn.workflow_key,
            workflow_version=defn.version,
            trigger_type=trigger_type,
            trigger_payload=payload or {},
            steps=[s.to_dict() for s in defn.steps],
            requested_by_user_id=requested_by_user_id,
            trigger_dedup_key=dedup_key,
            priority=priority,
        )
        if not created:
            return run

        self.audit.record(
            actor_id=actor_id or requested_by_user_id or "system",
            event_type="workflow.triggered",
            resource=f"workflow:{defn.workflow_key}@{defn.version}",
            decision="CREATED",
            details={"trigger_type": trigger_type, "dedup_key": dedup_key},
            run_id=run["id"],
        )

        if execute_async:
            self._schedule_run_execution(run["id"])
            return self.store.get_run(run["id"]) or run

        return self.execute_run(run["id"])

    def _schedule_run_execution(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        if run is None:
            return
        defn = self.registry.get(run["workflow_key"], run["workflow_version"])
        primary_lane = "compute_heavy" if any(s.lane == "compute_heavy" for s in defn.steps) else "control_ops"
        self.queue.submit(run_id, primary_lane, self.execute_run, run_id)

    def decide_approval_and_resume(
        self,
        approval_id: str,
        *,
        approve: bool,
        approver_user_id: str,
        approver_role: str,
        reason: str = "",
        execute_async: bool = False,
    ) -> dict[str, Any]:
        decided = self.governance.decide_approval(
            approval_id,
            approve=approve,
            approver_user_id=approver_user_id,
            approver_role=approver_role,
            reason=reason,
        )
        run_id = decided["run_id"]
        step_key = decided["step_key"]
        self.audit.record(
            actor_id=approver_user_id,
            event_type="workflow.approval_decision",
            resource=f"approval:{approval_id}",
            decision=decided["status"].upper(),
            details={"step_key": step_key, "reason": reason},
            run_id=run_id,
            step_key=step_key,
        )

        if not approve:
            self.store.update_step(
                run_id,
                step_key,
                status="BLOCKED",
                error_code="approval_rejected",
                finished_at=utc_now_iso(),
            )
            self.store.update_run(
                run_id,
                status="BLOCKED",
                error_message=f"Approval rejected for step {step_key}: {redact_text(reason or 'rejected')}",
                finished_at=utc_now_iso(),
            )
            return self.store.get_run(run_id) or {}

        self.store.update_step(run_id, step_key, status="PENDING")
        self.store.update_run(run_id, status="PENDING", error_message="")
        if execute_async:
            self._schedule_run_execution(run_id)
            return self.store.get_run(run_id) or {}
        return self.execute_run(run_id)

    def cancel_run(self, run_id: str, *, actor_id: str, reason: str = "cancelled_by_user") -> dict[str, Any] | None:
        run = self.store.get_run(run_id)
        if run is None:
            return None
        if run["status"] in ("COMPLETED", "FAILED", "BLOCKED", "CANCELLED"):
            return run
        self.store.update_run(
            run_id,
            status="CANCELLED",
            error_message=redact_text(reason),
            finished_at=utc_now_iso(),
        )
        self.audit.record(
            actor_id=actor_id,
            event_type="workflow.cancelled",
            resource=f"workflow_run:{run_id}",
            decision="CANCELLED",
            details={"reason": reason},
            run_id=run_id,
        )
        return self.store.get_run(run_id)

    def execute_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(f"Unknown workflow run: {run_id}")
        if run["status"] in ("COMPLETED", "FAILED", "BLOCKED", "CANCELLED"):
            return run

        defn: WorkflowDefinition = self.registry.get(run["workflow_key"], run["workflow_version"])
        now = utc_now_iso()
        if not run["started_at"]:
            self.store.update_run(run_id, status="RUNNING", started_at=now)
        else:
            self.store.update_run(run_id, status="RUNNING")

        payload = run["trigger_payload"] or {}
        previous_outputs: dict[str, Any] = {
            s["step_key"]: s["output"]
            for s in run["steps"]
            if s["status"] == "COMPLETED" and isinstance(s.get("output"), dict)
        }

        while True:
            current_run = self.store.get_run(run_id)
            if current_run is None or current_run["status"] == "CANCELLED":
                return current_run or run

            step_records = {s["step_key"]: s for s in current_run["steps"]}
            runnable, to_skip = resolve_ready_steps(defn.steps, step_records)

            for sk in to_skip:
                self.store.update_step(
                    run_id,
                    sk,
                    status="SKIPPED",
                    finished_at=utc_now_iso(),
                )

            if not runnable:
                break

            step = runnable[0]
            outcome = self._execute_single_step(
                run_id=run_id,
                defn=defn,
                step=step,
                step_record=step_records[step.step_key],
                payload=payload,
                previous_outputs=previous_outputs,
                requested_by_user_id=current_run.get("requested_by_user_id"),
            )
            if outcome == "PAUSE":
                return self.store.get_run(run_id) or current_run
            if outcome == "ABORT":
                return self.store.get_run(run_id) or current_run

            refreshed = self.store.get_run(run_id)
            if refreshed:
                for sr in refreshed["steps"]:
                    if sr["status"] == "COMPLETED" and isinstance(sr.get("output"), dict):
                        previous_outputs[sr["step_key"]] = sr["output"]

        final_run = self.store.get_run(run_id) or current_run
        statuses = {s["status"] for s in final_run["steps"]}
        if "BLOCKED" in statuses:
            final_status = "BLOCKED"
        elif "FAILED" in statuses:
            final_status = "FAILED"
        elif "WAITING_APPROVAL" in statuses:
            final_status = "WAITING_APPROVAL"
        elif "WAITING_RESOURCE" in statuses:
            final_status = "WAITING_RESOURCE"
        else:
            final_status = "COMPLETED"

        self.store.update_run(
            run_id,
            status=final_status,
            finished_at=utc_now_iso() if final_status in ("COMPLETED", "FAILED", "BLOCKED") else None,
        )
        self.audit.record(
            actor_id="system:orchestrator",
            event_type="workflow.finished",
            resource=f"workflow_run:{run_id}",
            decision=final_status,
            details={"step_statuses": {s["step_key"]: s["status"] for s in final_run["steps"]}},
            run_id=run_id,
        )
        return self.store.get_run(run_id) or final_run

    def _execute_single_step(
        self,
        *,
        run_id: str,
        defn: WorkflowDefinition,
        step: WorkflowStepSpec,
        step_record: dict[str, Any],
        payload: dict[str, Any],
        previous_outputs: dict[str, Any],
        requested_by_user_id: str | None,
    ) -> str:
        # 1. Resource Guard pre-flight check (paid GPU requires verified HMAC governance approval)
        has_paid_gpu_approval = self.governance.has_valid_approval(
            run_id, action_type="compute.paid_gpu"
        )
        if payload.get("approved_paid_gpu") and not has_paid_gpu_approval:
            self.audit.record(
                actor_id=requested_by_user_id or "system:orchestrator",
                event_type="workflow.paid_gpu_bypass_rejected",
                resource=f"step:{step.step_key}",
                decision="BLOCKED",
                details={"reason": "payload_boolean_paid_gpu_bypass_not_permitted"},
                run_id=run_id,
                step_key=step.step_key,
            )
        res_check = self.resource_guard.check_step(
            step, payload, has_paid_gpu_approval=has_paid_gpu_approval
        )
        self.store.update_run(run_id, resource_snapshot=res_check.snapshot)

        if not res_check.allowed:
            target_status = "BLOCKED" if res_check.blocked else "WAITING_RESOURCE"
            self.store.update_step(
                run_id,
                step.step_key,
                status=target_status,
                error_code="resource_blocked" if res_check.blocked else "resource_wait",
                finished_at=utc_now_iso() if res_check.blocked else None,
            )
            self.store.update_run(
                run_id,
                status=target_status,
                error_message=res_check.reason,
                finished_at=utc_now_iso() if res_check.blocked else None,
            )
            self.audit.record(
                actor_id="system:resource_guard",
                event_type="workflow.resource_check",
                resource=f"step:{step.step_key}",
                decision=target_status,
                details={"reason": res_check.reason, "snapshot": res_check.snapshot},
                run_id=run_id,
                step_key=step.step_key,
            )
            return "ABORT" if res_check.blocked else "PAUSE"

        # 2. Tier-2 Human Approval Gate
        consumed_approval: dict[str, Any] | None = None
        expected_step_scope = f"{defn.workflow_key}:{step.step_key}"
        if self.governance.requires_human_approval(step):
            try:
                consumed_approval = self.governance.verify_and_consume(
                    run_id, step, expected_scope=expected_step_scope
                )
            except ApprovalViolationError as exc:
                self.store.update_step(
                    run_id,
                    step.step_key,
                    status="BLOCKED",
                    error_code=exc.error_code,
                    finished_at=utc_now_iso(),
                )
                self.store.update_run(
                    run_id,
                    status="BLOCKED",
                    error_message=str(exc),
                    finished_at=utc_now_iso(),
                )
                self.audit.record(
                    actor_id="system:governance",
                    event_type="workflow.approval_violation",
                    resource=f"step:{step.step_key}",
                    decision="BLOCKED",
                    details={"error": str(exc)},
                    run_id=run_id,
                    step_key=step.step_key,
                )
                return "ABORT"

            if consumed_approval is None:
                approval = self.governance.ensure_pending_approval(
                    run_id=run_id,
                    step=step,
                    requested_by_user_id=requested_by_user_id,
                    scope=f"{defn.workflow_key}:{step.step_key}",
                    reason=step.description,
                )
                self.store.update_step(run_id, step.step_key, status="WAITING_APPROVAL")
                self.store.update_run(
                    run_id,
                    status="WAITING_APPROVAL",
                    error_message=f"Awaiting Tier-2 admin approval ({approval['id']}) for step {step.step_key}",
                )
                self.audit.record(
                    actor_id="system:governance",
                    event_type="workflow.approval_requested",
                    resource=f"approval:{approval['id']}",
                    decision="WAITING_APPROVAL",
                    details={"action_type": step.action_type, "scope": approval["scope"]},
                    run_id=run_id,
                    step_key=step.step_key,
                )
                return "PAUSE"

        # 3. Execute step handler with bounded retry & verification
        handler = self.registry.get_handler(step.handler_key)
        attempt = int(step_record.get("attempt", 0))
        while attempt < step.max_attempts:
            attempt += 1
            self.store.update_step(
                run_id,
                step.step_key,
                status="RUNNING",
                attempt=attempt,
                started_at=utc_now_iso(),
            )
            try:
                ctx = {
                    "run_id": run_id,
                    "step_key": step.step_key,
                    "resource_guard": self.resource_guard,
                    "audit": self.audit,
                    "previous_outputs": previous_outputs,
                    "consumed_approval": consumed_approval,
                }
                result: StepExecutionResult = handler(ctx, payload)
                self.store.update_run(run_id, status="VERIFYING")

                step_final_status = (
                    "COMPLETED"
                    if result.verdict == "PASS"
                    else ("BLOCKED" if result.verdict in ("BLOCKED", "NOT RUN") else "FAILED")
                )
                evidence_payload = {
                    "verdict": result.verdict,
                    "summary": result.summary,
                    **result.evidence,
                }
                self.store.update_step(
                    run_id,
                    step.step_key,
                    status=step_final_status,
                    evidence=evidence_payload,
                    output=result.output,
                    error_code=result.error_code,
                    finished_at=utc_now_iso(),
                )
                self.store.update_run(
                    run_id,
                    checkpoint_cursor={"last_step": step.step_key, "verdict": result.verdict},
                    error_message="" if step_final_status == "COMPLETED" else result.summary,
                )
                self.audit.record(
                    actor_id="system:orchestrator",
                    event_type="workflow.step_finished",
                    resource=f"step:{step.step_key}",
                    decision=result.verdict,
                    details={"summary": result.summary, "attempt": attempt},
                    run_id=run_id,
                    step_key=step.step_key,
                )

                for ev_name, ev_payload in result.emitted_events:
                    self.event_bus.emit(
                        ev_name,
                        ev_payload,
                        dedup_key=f"{run_id}:{step.step_key}:{ev_name}",
                    )

                if step_final_status in ("FAILED", "BLOCKED"):
                    self.store.update_run(
                        run_id,
                        status=step_final_status,
                        error_message=result.summary,
                        finished_at=utc_now_iso(),
                    )
                    return "ABORT"
                return "CONTINUE"

            except Exception as exc:
                retryable, err_code, target_run_status = self.recovery.classify_exception(exc)
                if not retryable or attempt >= step.max_attempts:
                    step_stat = "BLOCKED" if target_run_status == "BLOCKED" else "FAILED"
                    self.store.update_step(
                        run_id,
                        step.step_key,
                        status=step_stat,
                        error_code=err_code,
                        evidence={"verdict": step_stat, "error": redact_text(exc)},
                        finished_at=utc_now_iso(),
                    )
                    self.store.update_run(
                        run_id,
                        status=target_run_status,
                        error_message=redact_text(exc),
                        finished_at=utc_now_iso(),
                    )
                    self.audit.record(
                        actor_id="system:recovery",
                        event_type="workflow.step_aborted",
                        resource=f"step:{step.step_key}",
                        decision=target_run_status,
                        details={"error_code": err_code, "retryable": retryable, "attempt": attempt},
                        run_id=run_id,
                        step_key=step.step_key,
                    )
                    return "ABORT"

                retry_at = self.recovery.compute_backoff_until(attempt, step.retry_backoff_sec)
                self.store.update_step(
                    run_id,
                    step.step_key,
                    status="PENDING",
                    next_retry_at=retry_at,
                    error_code=err_code,
                )
                time.sleep(min(0.25, step.retry_backoff_sec))

        return "ABORT"

    # ------------------------------------------------------------------
    # Tier-2 HMAC-Verified Model Registry Lifecycle Operations
    # ------------------------------------------------------------------
    def _consume_lifecycle_approval(
        self,
        *,
        approval_id: str,
        expected_action_type: str,
        actor_id: str,
        resource: str,
        expected_model_version: str | None = None,
        expected_run_id: str | None = None,
    ) -> dict[str, Any]:
        token_id = str(approval_id or "").strip()
        if not token_id:
            self.audit.record(
                actor_id=actor_id,
                event_type=f"{expected_action_type}.approval_denied",
                resource=resource,
                decision="DENIED",
                details={"reason": "missing_approval_id"},
            )
            raise ApprovalViolationError(
                f"Tier-2 approval_id is required for {expected_action_type}."
            )
        try:
            consumed = self.governance.verify_and_consume_by_id(
                token_id,
                expected_action_type=expected_action_type,
                expected_run_id=expected_run_id,
                expected_scope=resource,
                expected_model_version=expected_model_version,
            )
        except ApprovalViolationError as exc:
            self.audit.record(
                actor_id=actor_id,
                event_type=f"{expected_action_type}.approval_denied",
                resource=resource,
                decision="DENIED",
                details={"approval_id": token_id, "reason": str(exc)},
            )
            raise
        return consumed

    def stage_model_with_approval(
        self,
        registry: Any,
        version: str,
        *,
        approval_id: str,
        actor_id: str,
        reason: str = "",
        expected_run_id: str | None = None,
    ) -> dict[str, Any]:
        consumed = self._consume_lifecycle_approval(
            approval_id=approval_id,
            expected_action_type="model.stage",
            actor_id=actor_id,
            resource=f"model:{version}",
            expected_model_version=version,
            expected_run_id=expected_run_id,
        )
        compat = registry.check_compatibility(version)
        if not compat["compatible"]:
            from apps.core.native.registry import RegistryError

            self.audit.record(
                actor_id=actor_id,
                event_type="model.stage.failed",
                resource=f"model:{version}",
                decision="FAILED",
                details={"approval_id": consumed["id"], "reasons": compat["reasons"]},
            )
            raise RegistryError(f"Compatibility check failed: {compat['reasons']}")
        rec = registry.set_lifecycle_status(
            version,
            "staging",
            approval_id=consumed["id"],
            approved_by=actor_id,
            reason=reason,
        )
        self.audit.record(
            actor_id=actor_id,
            event_type="model.stage.completed",
            resource=f"model:{version}",
            decision="STAGED",
            details={"approval_id": consumed["id"], "reason": reason},
        )
        return {"status": "staged", "record": rec, "compatibility": compat}

    def promote_model_with_approval(
        self,
        registry: Any,
        version: str,
        *,
        approval_id: str,
        actor_id: str,
        expected_run_id: str | None = None,
    ) -> dict[str, Any]:
        consumed = self._consume_lifecycle_approval(
            approval_id=approval_id,
            expected_action_type="model.promote",
            actor_id=actor_id,
            resource=f"model:{version}",
            expected_model_version=version,
            expected_run_id=expected_run_id,
        )
        try:
            registry.promote(
                version,
                enforce_evaluation_gate=True,
                approval_id=consumed["id"],
                approved_by=actor_id,
            )
        except Exception as exc:
            self.audit.record(
                actor_id=actor_id,
                event_type="model.promote.failed",
                resource=f"model:{version}",
                decision="FAILED",
                details={"approval_id": consumed["id"], "error": str(exc)},
            )
            raise
        self.audit.record(
            actor_id=actor_id,
            event_type="model.promote.completed",
            resource=f"model:{version}",
            decision="PROMOTED",
            details={"approval_id": consumed["id"], "active_version": registry.active_version()},
        )
        return {
            "status": "promoted",
            "active_version": registry.active_version(),
            "record": registry.get(version),
        }

    def rollback_model_with_approval(
        self,
        registry: Any,
        *,
        to_version: str | None = None,
        approval_id: str,
        actor_id: str,
        expected_run_id: str | None = None,
    ) -> dict[str, Any]:
        target_label = to_version or "previous"
        consumed = self._consume_lifecycle_approval(
            approval_id=approval_id,
            expected_action_type="model.rollback",
            actor_id=actor_id,
            resource=f"model:{target_label}",
            expected_model_version=target_label,
            expected_run_id=expected_run_id,
        )
        try:
            target = registry.rollback(to_version, approval_id=consumed["id"])
        except Exception as exc:
            self.audit.record(
                actor_id=actor_id,
                event_type="model.rollback.failed",
                resource=f"model:{to_version or 'previous'}",
                decision="FAILED",
                details={"approval_id": consumed["id"], "error": str(exc)},
            )
            raise
        self.audit.record(
            actor_id=actor_id,
            event_type="model.rollback.completed",
            resource=f"model:{target}",
            decision="ROLLED_BACK",
            details={"approval_id": consumed["id"], "active_version": target},
        )
        return {
            "status": "rolled_back",
            "active_version": target,
            "record": registry.get(target),
        }

