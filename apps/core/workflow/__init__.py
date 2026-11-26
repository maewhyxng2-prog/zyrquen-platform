"""ZYRQUEN Central Native Workflow Engine & Tier-2 Approval Gate Registry (pure stdlib)."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from apps.core.workflow.governance import (
    ApprovalViolationError,
    WorkflowGovernance,
    WorkflowStepSpec,
)
from apps.core.workflow.handlers.groups import (
    handle_dataset_ingest,
    handle_evaluation_gate,
    handle_training_execute,
)

WORKFLOW_GROUPS: tuple[str, ...] = (
    "data_pipeline",
    "native_training",
    "evaluation",
    "model_registry",
    "memory_kg",
    "research",
    "autonomous_ops",
    "governance",
)


class WorkflowValidationError(ValueError):
    """Raised when workflow definitions, DAG steps, or triggers are invalid."""


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_key: str
    version: str
    group_name: str
    title: str
    description: str
    default_tier: str = "tier1_auto"
    schedule_interval_sec: int | None = None
    event_triggers: tuple[str, ...] = field(default_factory=tuple)
    steps: tuple[WorkflowStepSpec, ...] = field(default_factory=tuple)


class WorkflowStore:
    """Thread-safe SQLite WAL persistence store for workflow runs, approvals, and audit logs."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve(strict=False)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workflow_definitions (
                id TEXT PRIMARY KEY,
                workflow_key TEXT NOT NULL,
                version TEXT NOT NULL,
                group_name TEXT NOT NULL,
                dag_spec_json TEXT NOT NULL,
                default_tier TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                UNIQUE(workflow_key, version)
            );

            CREATE TABLE IF NOT EXISTS workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_key TEXT NOT NULL,
                workflow_version TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_dedup_key TEXT UNIQUE,
                trigger_payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 50,
                requested_by_user_id TEXT,
                steps_json TEXT NOT NULL DEFAULT '[]',
                error_message TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS workflow_step_runs (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                step_key TEXT NOT NULL,
                handler_key TEXT NOT NULL,
                status TEXT NOT NULL,
                output_json TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT,
                UNIQUE(run_id, step_key),
                FOREIGN KEY(run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS workflow_approvals (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                step_key TEXT NOT NULL,
                action_type TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT '',
                requested_by_user_id TEXT,
                approved_by_user_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                signature_hmac TEXT,
                expires_at TEXT NOT NULL,
                consumed_at TEXT,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS workflow_audit_logs (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                step_key TEXT,
                actor_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                resource TEXT NOT NULL,
                decision TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _row_to_run(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        d = dict(row)
        d["trigger_payload"] = json.loads(d.pop("trigger_payload_json", "{}") or "{}")
        d["steps"] = json.loads(d.pop("steps_json", "[]") or "[]")
        return d

    def upsert_definition(self, defn: WorkflowDefinition) -> None:
        now = datetime.now(timezone.utc).isoformat()
        dag_spec = json.dumps([s.to_dict() for s in defn.steps], ensure_ascii=False)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO workflow_definitions (id, workflow_key, version, group_name, dag_spec_json, default_tier, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(workflow_key, version) DO UPDATE SET
                    group_name=excluded.group_name,
                    dag_spec_json=excluded.dag_spec_json,
                    default_tier=excluded.default_tier
                """,
                (str(uuid.uuid4()), defn.workflow_key, defn.version, defn.group_name, dag_spec, defn.default_tier, now),
            )

    def create_run(
        self,
        *,
        workflow_key: str,
        workflow_version: str = "1.0.0",
        trigger_type: str = "manual",
        trigger_payload: dict[str, Any] | None = None,
        steps: list[dict[str, Any]] | None = None,
        requested_by_user_id: str | None = None,
        dedup_key: str | None = None,
        status: str = "pending",
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(trigger_payload or {}, ensure_ascii=False)
        steps_list = list(steps or [])
        steps_json = json.dumps(steps_list, ensure_ascii=False)

        with self._lock:
            if dedup_key:
                existing = self._conn.execute(
                    "SELECT * FROM workflow_runs WHERE trigger_dedup_key=?",
                    (dedup_key,),
                ).fetchone()
                if existing is not None:
                    step_rows = [
                        dict(r)
                        for r in self._conn.execute(
                            "SELECT * FROM workflow_step_runs WHERE run_id=? ORDER BY rowid ASC",
                            (existing["id"],),
                        ).fetchall()
                    ]
                    return self._row_to_run(existing) or {}, step_rows

            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO workflow_runs (
                        id, workflow_key, workflow_version, trigger_type, trigger_dedup_key,
                        trigger_payload_json, status, priority, requested_by_user_id, steps_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 50, ?, ?, ?)
                    """,
                    (
                        run_id,
                        workflow_key,
                        workflow_version,
                        trigger_type,
                        dedup_key,
                        payload_json,
                        status,
                        requested_by_user_id,
                        steps_json,
                        now,
                    ),
                )
                step_records: list[dict[str, Any]] = []
                for step in steps_list:
                    step_id = str(uuid.uuid4())
                    skey = str(step.get("step_key") or "step")
                    hkey = str(step.get("handler_key") or skey)
                    self._conn.execute(
                        """
                        INSERT INTO workflow_step_runs (id, run_id, step_key, handler_key, status, created_at)
                        VALUES (?, ?, ?, ?, 'pending', ?)
                        """,
                        (step_id, run_id, skey, hkey, now),
                    )
                    step_records.append(
                        {
                            "id": step_id,
                            "run_id": run_id,
                            "step_key": skey,
                            "handler_key": hkey,
                            "status": "pending",
                            "created_at": now,
                        }
                    )
            run_row = self._conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone()
            return self._row_to_run(run_row) or {}, step_records

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM workflow_runs WHERE id=?", (str(run_id),)).fetchone()
            return self._row_to_run(row)

    def update_run_status(
        self,
        run_id: str,
        *,
        status: str,
        error_message: str | None = None,
        finished: bool = False,
    ) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn:
            if finished:
                self._conn.execute(
                    "UPDATE workflow_runs SET status=?, error_message=?, finished_at=? WHERE id=?",
                    (status, error_message, now, str(run_id)),
                )
            else:
                self._conn.execute(
                    "UPDATE workflow_runs SET status=?, error_message=? WHERE id=?",
                    (status, error_message, str(run_id)),
                )
        return self.get_run(run_id)

    def list_runs(
        self,
        *,
        status: str | None = None,
        workflow_key: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if workflow_key:
            clauses.append("workflow_key = ?")
            params.append(workflow_key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(200, int(limit))))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM workflow_runs {where} ORDER BY created_at DESC, rowid DESC LIMIT ?",
                tuple(params),
            ).fetchall()
            return [r for r in (self._row_to_run(row) for row in rows) if r is not None]

    def create_approval(
        self,
        *,
        approval_id: str,
        run_id: str,
        step_key: str,
        action_type: str,
        scope: str,
        requested_by_user_id: str | None,
        status: str,
        expires_at: str,
        created_at: str,
    ) -> dict[str, Any]:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO workflow_approvals (
                    id, run_id, step_key, action_type, scope, requested_by_user_id,
                    status, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_id,
                    run_id,
                    step_key,
                    action_type,
                    scope,
                    requested_by_user_id,
                    status,
                    expires_at,
                    created_at,
                ),
            )
        return self.get_approval(approval_id) or {}

    def find_approval_for_step(self, *, run_id: str, step_key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM workflow_approvals WHERE run_id=? AND step_key=? ORDER BY created_at DESC LIMIT 1",
                (str(run_id), str(step_key)),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM workflow_approvals WHERE id=?",
                (str(approval_id),),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_approvals(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(200, int(limit)))
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM workflow_approvals WHERE status=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (status, safe_limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM workflow_approvals ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def update_approval(
        self,
        approval_id: str,
        *,
        status: str,
        approved_by_user_id: str | None,
        signature_hmac: str | None,
        reason: str = "",
    ) -> dict[str, Any]:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE workflow_approvals
                SET status=?, approved_by_user_id=?, signature_hmac=?, reason=?
                WHERE id=?
                """,
                (status, approved_by_user_id, signature_hmac, reason, str(approval_id)),
            )
        return self.get_approval(approval_id) or {}

    def consume_approval(self, approval_id: str, *, consumed_at: str) -> dict[str, Any] | None:
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                UPDATE workflow_approvals
                SET status='consumed', consumed_at=?
                WHERE id=? AND status='approved'
                """,
                (consumed_at, str(approval_id)),
            )
            if cur.rowcount != 1:
                return None
        return self.get_approval(approval_id)

    def append_audit_log(
        self,
        *,
        run_id: str | None,
        step_key: str | None,
        actor_id: str,
        event_type: str,
        resource: str,
        decision: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        log_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        details_json = json.dumps(details or {}, ensure_ascii=False)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO workflow_audit_logs (
                    id, run_id, step_key, actor_id, event_type, resource, decision, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (log_id, run_id, step_key, actor_id, event_type, resource, decision, details_json, now),
            )
        return {
            "id": log_id,
            "run_id": run_id,
            "step_key": step_key,
            "actor_id": actor_id,
            "event_type": event_type,
            "resource": resource,
            "decision": decision,
            "details": details or {},
            "created_at": now,
        }

    def list_audit_logs(self, *, run_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(500, int(limit)))
        with self._lock:
            if run_id:
                rows = self._conn.execute(
                    "SELECT * FROM workflow_audit_logs WHERE run_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (str(run_id), safe_limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM workflow_audit_logs ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                d = dict(row)
                d["details"] = json.loads(d.pop("details_json", "{}") or "{}")
                out.append(d)
            return out


class WorkflowRegistry:
    """In-memory + SQLite-synced registry of WorkflowDefinitions and step handlers."""

    def __init__(self, store: WorkflowStore) -> None:
        self._store = store
        self._definitions: dict[tuple[str, str], WorkflowDefinition] = {}
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    def register(self, definition: WorkflowDefinition) -> WorkflowDefinition:
        if definition.group_name not in WORKFLOW_GROUPS:
            raise WorkflowValidationError(
                f"Unknown workflow group {definition.group_name!r}; expected one of {WORKFLOW_GROUPS}"
            )
        self._definitions[(definition.workflow_key, definition.version)] = definition
        self._store.upsert_definition(definition)
        return definition

    def register_handler(
        self,
        handler_key: str,
        fn: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._handlers[str(handler_key)] = fn

    def get(self, workflow_key: str, version: str | None = None) -> WorkflowDefinition:
        if version is not None:
            defn = self._definitions.get((workflow_key, version))
            if defn is None:
                raise WorkflowValidationError(f"Workflow definition not found: {workflow_key}@{version}")
            return defn
        candidates = [d for (wk, _), d in self._definitions.items() if wk == workflow_key]
        if not candidates:
            raise WorkflowValidationError(f"Workflow definition not found: {workflow_key}")
        return sorted(candidates, key=lambda d: d.version, reverse=True)[0]

    def get_handler(self, handler_key: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        fn = self._handlers.get(handler_key)
        if fn is None:
            raise WorkflowValidationError(f"Workflow handler not registered: {handler_key}")
        return fn

    def list_definitions(self, *, group_name: str | None = None) -> list[WorkflowDefinition]:
        items = list(self._definitions.values())
        if group_name:
            items = [d for d in items if d.group_name == group_name]
        return sorted(items, key=lambda d: (d.group_name, d.workflow_key, d.version))


class WorkflowScheduler:
    def __init__(self) -> None:
        self._running = False

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def is_running(self) -> bool:
        return self._running


class CentralWorkflowOrchestrator:
    """Central Workflow Orchestrator coordinating Registry, Store, and Tier-2 Governance."""

    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        work_dir: str | Path | None = None,
        approval_secret: str | None = None,
    ) -> None:
        resolved_work = Path(work_dir) if work_dir is not None else Path(tempfile.gettempdir()) / "zyrquen_workflow"
        resolved_work.mkdir(parents=True, exist_ok=True)
        self.work_dir = resolved_work

        env_db = os.getenv("ZYRQUEN_WORKFLOW_DB_PATH", "").strip()
        resolved_db = Path(db_path) if db_path is not None else (Path(env_db) if env_db else resolved_work / "workflow.db")
        resolved_secret = approval_secret if approval_secret is not None else os.getenv("ZYRQUEN_APPROVAL_SECRET", "")

        self.store = WorkflowStore(resolved_db)
        self.registry = WorkflowRegistry(self.store)
        self.governance = WorkflowGovernance(self.store, approval_secret=resolved_secret)
        self.scheduler = WorkflowScheduler()
        self._started = False
        self._recovery_enabled = False
        self._register_builtin_workflows()

    def _register_builtin_workflows(self) -> None:
        self.registry.register_handler("dataset.ingest", handle_dataset_ingest)
        self.registry.register_handler("training.execute", handle_training_execute)
        self.registry.register_handler("evaluation.gate", handle_evaluation_gate)

        self.registry.register(
            WorkflowDefinition(
                workflow_key="dataset.governed_ingest",
                version="1.0.0",
                group_name="data_pipeline",
                title="Governed V11 Dataset Ingestion & Readiness Gate",
                description="Requires Tier-2 Approval Gate ticket before marking an ingested dataset as ready for training.",
                default_tier="tier2_approval",
                steps=(
                    WorkflowStepSpec(
                        step_key="approve_dataset_ingest",
                        handler_key="dataset.ingest",
                        description="Approve V11 dataset ingestion into the training pipeline",
                        tier="tier2_approval",
                        action_type="dataset.ingest",
                    ),
                ),
            )
        )
        self.registry.register(
            WorkflowDefinition(
                workflow_key="training.native_controlled_run",
                version="1.0.0",
                group_name="native_training",
                title="Governed Native Training Run",
                description="Requires Tier-2 Approval Gate ticket before launching native training.",
                default_tier="tier2_approval",
                steps=(
                    WorkflowStepSpec(
                        step_key="execute_training",
                        handler_key="training.execute",
                        description="Execute native model training run",
                        tier="tier2_approval",
                        action_type="training.execute",
                    ),
                ),
            )
        )
        self.registry.register(
            WorkflowDefinition(
                workflow_key="evaluation.v10_gate",
                version="1.0.0",
                group_name="evaluation",
                title="Scientific Evaluation Gate",
                description="Verifies V10 scientific evaluation metrics and anti-False-PASS checks.",
                default_tier="tier1_auto",
                steps=(
                    WorkflowStepSpec(
                        step_key="evaluation_gate",
                        handler_key="evaluation.gate",
                        description="Evaluate candidate checkpoint against scientific benchmarks",
                        tier="tier1_auto",
                        action_type="evaluation.gate",
                    ),
                ),
            )
        )

    def start(self, *, enable_scheduler: bool = True, enable_recovery: bool = True) -> None:
        self._started = True
        self._recovery_enabled = bool(enable_recovery)
        if enable_scheduler:
            self.scheduler.start()

    def shutdown(self, wait: bool = True) -> None:
        self.scheduler.stop()
        self._started = False
        self.store.close()

    def get_service_status(self) -> dict[str, Any]:
        return {
            "started": self._started,
            "scheduler_running": self.scheduler.is_running(),
            "recovery_enabled": self._recovery_enabled,
            "registered_workflows": len(self.registry.list_definitions()),
        }

    def trigger_workflow(
        self,
        workflow_key: str,
        *,
        version: str | None = None,
        trigger_type: str = "manual",
        payload: dict[str, Any] | None = None,
        requested_by_user_id: str | None = None,
        actor_id: str = "system",
        dedup_key: str | None = None,
        execute_async: bool = False,
    ) -> dict[str, Any]:
        defn = self.registry.get(workflow_key, version=version)
        run, _ = self.store.create_run(
            workflow_key=defn.workflow_key,
            workflow_version=defn.version,
            trigger_type=trigger_type,
            trigger_payload=payload,
            steps=[s.to_dict() for s in defn.steps],
            requested_by_user_id=requested_by_user_id,
            dedup_key=dedup_key,
            status="running",
        )
        self.store.append_audit_log(
            run_id=run["id"],
            step_key=None,
            actor_id=actor_id,
            event_type="workflow_triggered",
            resource=f"workflow:{defn.workflow_key}@{defn.version}",
            decision="STARTED",
            details={"trigger_type": trigger_type},
        )

        scope = ""
        if isinstance(payload, dict) and payload.get("dataset_version"):
            scope = f"dataset:{payload['dataset_version']}"
        elif isinstance(payload, dict) and payload.get("scope"):
            scope = str(payload["scope"])

        for step in defn.steps:
            if step.tier == "tier2_approval":
                approval = self.governance.ensure_pending_approval(
                    run_id=run["id"],
                    step=step,
                    requested_by_user_id=requested_by_user_id,
                    scope=scope,
                )
                updated = self.store.update_run_status(run["id"], status="awaiting_approval")
                if updated is not None:
                    updated["pending_approval_id"] = approval["id"]
                    return updated
                return run

        updated = self.store.update_run_status(run["id"], status="completed", finished=True)
        return updated or run

    def cancel_run(self, run_id: str, *, actor_id: str = "system") -> dict[str, Any]:
        updated = self.store.update_run_status(run_id, status="cancelled", finished=True)
        if updated is None:
            raise WorkflowValidationError(f"Workflow run not found: {run_id}")
        self.store.append_audit_log(
            run_id=run_id,
            step_key=None,
            actor_id=actor_id,
            event_type="workflow_cancelled",
            resource=f"run:{run_id}",
            decision="CANCELLED",
        )
        return updated

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
        next_status = "approved" if approve else "rejected"
        updated = self.store.update_run_status(run_id, status=next_status, finished=not approve)
        return updated or {"id": run_id, "status": next_status, "approval_id": approval_id}

    def stage_model_with_approval(
        self,
        registry: Any,
        version: str,
        *,
        approval_id: str | None,
        actor_id: str,
        reason: str = "",
    ) -> dict[str, Any]:
        if not approval_id:
            raise ApprovalViolationError("approval_id is required to stage model version.")
        self.governance.verify_and_consume_by_id(approval_id, expected_action_type="model.stage")
        return registry.stage(version, approved_by=actor_id, approval_id=approval_id, reason=reason)

    def promote_model_with_approval(
        self,
        registry: Any,
        version: str,
        *,
        approval_id: str | None,
        actor_id: str,
    ) -> dict[str, Any]:
        if not approval_id:
            raise ApprovalViolationError("approval_id is required to promote model version.")
        self.governance.verify_and_consume_by_id(approval_id, expected_action_type="model.promote")
        return registry.promote(version, approved_by=actor_id, approval_id=approval_id)

    def rollback_model_with_approval(
        self,
        registry: Any,
        *,
        to_version: str | None,
        approval_id: str | None,
        actor_id: str,
    ) -> dict[str, Any]:
        if not approval_id:
            raise ApprovalViolationError("approval_id is required to rollback model version.")
        self.governance.verify_and_consume_by_id(approval_id, expected_action_type="model.rollback")
        rolled_to = registry.rollback(to_version, approval_id=approval_id)
        return {"active_version": rolled_to, "approval_id": approval_id, "actor_id": actor_id}


def create_default_orchestrator() -> CentralWorkflowOrchestrator:
    data_dir = os.getenv("ZYRQUEN_DATA_DIR", "").strip()
    work_dir = Path(data_dir) / "workflow" if data_dir else None
    return CentralWorkflowOrchestrator(work_dir=work_dir)


__all__ = [
    "ApprovalViolationError",
    "CentralWorkflowOrchestrator",
    "WORKFLOW_GROUPS",
    "WorkflowDefinition",
    "WorkflowGovernance",
    "WorkflowRegistry",
    "WorkflowStepSpec",
    "WorkflowStore",
    "WorkflowValidationError",
    "create_default_orchestrator",
]
