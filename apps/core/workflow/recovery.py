"""Step checkpointing, bounded retries, non-retryable abort rules, and startup reconciliation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from apps.core.workflow.audit import WorkflowAuditLogger
from apps.core.workflow.models import NonRetryableWorkflowError, utc_now_iso
from apps.core.workflow.queue import DualLaneTaskQueue
from apps.core.workflow.store import WorkflowStore


class RecoveryManager:
    def __init__(self, store: WorkflowStore, audit: WorkflowAuditLogger) -> None:
        self.store = store
        self.audit = audit

    def compute_backoff_until(self, attempt: int, base_backoff_sec: float) -> str:
        delay = min(60.0, max(0.05, base_backoff_sec) * (2 ** max(0, attempt - 1)))
        return (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()

    def classify_exception(self, exc: Exception) -> tuple[bool, str, str]:
        """Return (is_retryable, error_code, target_run_status)."""
        if isinstance(exc, NonRetryableWorkflowError):
            return False, exc.error_code, exc.target_run_status
        msg = str(exc).lower()
        if isinstance(exc, MemoryError) or "out of memory" in msg:
            return False, "out_of_memory", "FAILED"
        if "nan" in msg or "inf" in msg:
            return False, "nan_inf_loss", "FAILED"
        return True, type(exc).__name__, "FAILED"

    def reconcile_orphaned_runs(self, queue: DualLaneTaskQueue) -> list[str]:
        """Recover runs left in RUNNING/VERIFYING after an ungraceful process shutdown."""
        recovered: list[str] = []
        for status in ("RUNNING", "VERIFYING"):
            for run in self.store.list_runs(status=status, limit=200):
                run_id = run["id"]
                if queue.is_run_active(run_id):
                    continue
                for step in run["steps"]:
                    if step["status"] == "RUNNING":
                        # Mark interrupted step back to PENDING if attempts remain, else FAILED
                        if step["attempt"] < step["max_attempts"]:
                            self.store.update_step(
                                run_id,
                                step["step_key"],
                                status="PENDING",
                                error_code="worker_restarted",
                            )
                        else:
                            self.store.update_step(
                                run_id,
                                step["step_key"],
                                status="FAILED",
                                error_code="worker_crash_max_attempts",
                                finished_at=utc_now_iso(),
                            )
                self.store.update_run(run_id, status="PENDING", error_message="Recovered after worker restart")
                self.audit.record(
                    actor_id="system:recovery",
                    event_type="workflow.reconciled",
                    resource=f"workflow_run:{run_id}",
                    decision="REQUEUED",
                    details={"previous_status": status},
                    run_id=run_id,
                )
                recovered.append(run_id)
        return recovered
