"""Persistent SQLite storage backend for Workflow Engine state, approvals, and audit logs.

Standard-library SQLite store mirroring the 5-table PostgreSQL schema from
docs/WORKFLOW_ENGINE_PLAN.md Section 2 so the core workflow engine operates reliably
across CLI, worker processes, unit tests, and FastAPI runtime.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.core.workflow.models import utc_now_iso


class WorkflowStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def _conn(self):
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), timeout=15.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflow_definitions (
                    id TEXT PRIMARY KEY,
                    workflow_key TEXT NOT NULL,
                    version TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    dag_spec TEXT NOT NULL,
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
                    trigger_payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 50,
                    requested_by_user_id TEXT,
                    checkpoint_cursor TEXT,
                    resource_snapshot TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_wf_runs_status ON workflow_runs(status);
                CREATE INDEX IF NOT EXISTS ix_wf_runs_key ON workflow_runs(workflow_key, created_at);

                CREATE TABLE IF NOT EXISTS workflow_step_runs (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
                    step_key TEXT NOT NULL,
                    depends_on TEXT NOT NULL,
                    lane TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 2,
                    next_retry_at TEXT,
                    evidence TEXT,
                    output TEXT,
                    error_code TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    UNIQUE(run_id, step_key)
                );
                CREATE INDEX IF NOT EXISTS ix_wf_step_runs_run ON workflow_step_runs(run_id);

                CREATE TABLE IF NOT EXISTS workflow_approvals (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
                    step_key TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    requested_by_user_id TEXT,
                    approved_by_user_id TEXT,
                    status TEXT NOT NULL,
                    signature_hmac TEXT,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_wf_approvals_status ON workflow_approvals(status);

                CREATE TABLE IF NOT EXISTS workflow_audit_logs (
                    id TEXT PRIMARY KEY,
                    run_id TEXT,
                    step_key TEXT,
                    actor_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_wf_audit_run ON workflow_audit_logs(run_id);
                CREATE INDEX IF NOT EXISTS ix_wf_audit_created ON workflow_audit_logs(created_at);

                CREATE TABLE IF NOT EXISTS scheduler_state (
                    workflow_key TEXT PRIMARY KEY,
                    last_triggered_at TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS trg_wf_audit_no_update
                BEFORE UPDATE ON workflow_audit_logs
                BEGIN
                    SELECT RAISE(ABORT, 'workflow_audit_logs is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_wf_audit_no_delete
                BEFORE DELETE ON workflow_audit_logs
                BEGIN
                    SELECT RAISE(ABORT, 'workflow_audit_logs is append-only');
                END;
                """
            )

    @staticmethod
    def _decode_json(val: str | None, default: Any = None) -> Any:
        if val is None:
            return default
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return default

    def upsert_definition(
        self,
        workflow_key: str,
        version: str,
        group_name: str,
        dag_spec: dict[str, Any],
        default_tier: str,
        is_active: bool = True,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO workflow_definitions (id, workflow_key, version, group_name, dag_spec, default_tier, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_key, version) DO UPDATE SET
                    group_name = excluded.group_name,
                    dag_spec = excluded.dag_spec,
                    default_tier = excluded.default_tier,
                    is_active = excluded.is_active
                """,
                (
                    str(uuid.uuid4()),
                    workflow_key,
                    version,
                    group_name,
                    json.dumps(dag_spec, ensure_ascii=False),
                    default_tier,
                    1 if is_active else 0,
                    utc_now_iso(),
                ),
            )

    def create_run(
        self,
        *,
        workflow_key: str,
        workflow_version: str,
        trigger_type: str,
        trigger_payload: dict[str, Any],
        steps: list[dict[str, Any]],
        requested_by_user_id: str | None = None,
        trigger_dedup_key: str | None = None,
        priority: int = 50,
    ) -> tuple[dict[str, Any], bool]:
        """Create a workflow run and its step rows atomically.

        Returns (run_dict, created_new). If trigger_dedup_key already exists, returns existing run.
        """
        run_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self._conn() as conn:
            if trigger_dedup_key:
                existing = conn.execute(
                    "SELECT * FROM workflow_runs WHERE trigger_dedup_key = ?",
                    (trigger_dedup_key,),
                ).fetchone()
                if existing is not None:
                    return self._row_to_run(conn, existing), False

            conn.execute(
                """
                INSERT INTO workflow_runs (
                    id, workflow_key, workflow_version, trigger_type, trigger_dedup_key,
                    trigger_payload, status, priority, requested_by_user_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    workflow_key,
                    workflow_version,
                    trigger_type,
                    trigger_dedup_key,
                    json.dumps(trigger_payload, ensure_ascii=False),
                    "PENDING",
                    priority,
                    requested_by_user_id,
                    now,
                ),
            )
            for s in steps:
                conn.execute(
                    """
                    INSERT INTO workflow_step_runs (
                        id, run_id, step_key, depends_on, lane, status, attempt, max_attempts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        run_id,
                        s["step_key"],
                        json.dumps(s.get("depends_on", [])),
                        s.get("lane", "control_ops"),
                        "PENDING",
                        0,
                        int(s.get("max_attempts", 2)),
                    ),
                )
            row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
            return self._row_to_run(conn, row), True

    def _row_to_step(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "step_key": row["step_key"],
            "depends_on": self._decode_json(row["depends_on"], []),
            "lane": row["lane"],
            "status": row["status"],
            "attempt": row["attempt"],
            "max_attempts": row["max_attempts"],
            "next_retry_at": row["next_retry_at"],
            "evidence": self._decode_json(row["evidence"]),
            "output": self._decode_json(row["output"]),
            "error_code": row["error_code"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    def _row_to_run(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        step_rows = conn.execute(
            "SELECT * FROM workflow_step_runs WHERE run_id = ?",
            (row["id"],),
        ).fetchall()
        approvals = conn.execute(
            "SELECT * FROM workflow_approvals WHERE run_id = ? ORDER BY created_at DESC",
            (row["id"],),
        ).fetchall()
        return {
            "id": row["id"],
            "workflow_key": row["workflow_key"],
            "workflow_version": row["workflow_version"],
            "trigger_type": row["trigger_type"],
            "trigger_dedup_key": row["trigger_dedup_key"],
            "trigger_payload": self._decode_json(row["trigger_payload"], {}),
            "status": row["status"],
            "priority": row["priority"],
            "requested_by_user_id": row["requested_by_user_id"],
            "checkpoint_cursor": self._decode_json(row["checkpoint_cursor"]),
            "resource_snapshot": self._decode_json(row["resource_snapshot"]),
            "error_message": row["error_message"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "steps": [self._row_to_step(sr) for sr in step_rows],
            "approvals": [dict(a) for a in approvals],
        }

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            return self._row_to_run(conn, row)

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
        sql = f"SELECT * FROM workflow_runs {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [self._row_to_run(conn, r) for r in rows]

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        checkpoint_cursor: dict[str, Any] | None = None,
        resource_snapshot: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        fields: list[str] = []
        params: list[Any] = []
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if checkpoint_cursor is not None:
            fields.append("checkpoint_cursor = ?")
            params.append(json.dumps(checkpoint_cursor, ensure_ascii=False))
        if resource_snapshot is not None:
            fields.append("resource_snapshot = ?")
            params.append(json.dumps(resource_snapshot, ensure_ascii=False))
        if error_message is not None:
            fields.append("error_message = ?")
            params.append(error_message)
        if started_at is not None:
            fields.append("started_at = ?")
            params.append(started_at)
        if finished_at is not None:
            fields.append("finished_at = ?")
            params.append(finished_at)
        if not fields:
            return
        params.append(run_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE workflow_runs SET {', '.join(fields)} WHERE id = ?", tuple(params))

    def update_step(
        self,
        run_id: str,
        step_key: str,
        *,
        status: str | None = None,
        attempt: int | None = None,
        next_retry_at: str | None = None,
        evidence: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        error_code: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        fields: list[str] = []
        params: list[Any] = []
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if attempt is not None:
            fields.append("attempt = ?")
            params.append(attempt)
        if next_retry_at is not None:
            fields.append("next_retry_at = ?")
            params.append(next_retry_at)
        if evidence is not None:
            fields.append("evidence = ?")
            params.append(json.dumps(evidence, ensure_ascii=False))
        if output is not None:
            fields.append("output = ?")
            params.append(json.dumps(output, ensure_ascii=False))
        if error_code is not None:
            fields.append("error_code = ?")
            params.append(error_code)
        if started_at is not None:
            fields.append("started_at = ?")
            params.append(started_at)
        if finished_at is not None:
            fields.append("finished_at = ?")
            params.append(finished_at)
        if not fields:
            return
        params.extend([run_id, step_key])
        with self._conn() as conn:
            conn.execute(
                f"UPDATE workflow_step_runs SET {', '.join(fields)} WHERE run_id = ? AND step_key = ?",
                tuple(params),
            )

    def create_approval_request(
        self,
        *,
        run_id: str,
        step_key: str,
        action_type: str,
        scope: str,
        requested_by_user_id: str | None,
        expires_at: str,
        reason: str = "",
    ) -> dict[str, Any]:
        with self._conn() as conn:
            existing = conn.execute(
                """
                SELECT * FROM workflow_approvals
                WHERE run_id = ? AND step_key = ? AND status IN ('pending', 'approved')
                ORDER BY created_at DESC LIMIT 1
                """,
                (run_id, step_key),
            ).fetchone()
            if existing is not None:
                return dict(existing)

            approval_id = str(uuid.uuid4())
            now = utc_now_iso()
            conn.execute(
                """
                INSERT INTO workflow_approvals (
                    id, run_id, step_key, action_type, scope, requested_by_user_id,
                    status, expires_at, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    approval_id,
                    run_id,
                    step_key,
                    action_type,
                    scope,
                    requested_by_user_id,
                    expires_at,
                    reason,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM workflow_approvals WHERE id = ?", (approval_id,)).fetchone()
            return dict(row)

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM workflow_approvals WHERE id = ?", (approval_id,)).fetchone()
            return dict(row) if row is not None else None

    def list_approvals(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM workflow_approvals WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM workflow_approvals ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def set_approval_decision(
        self,
        approval_id: str,
        *,
        status: str,
        approved_by_user_id: str,
        signature_hmac: str | None,
        reason: str = "",
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE workflow_approvals
                SET status = ?, approved_by_user_id = ?, signature_hmac = ?,
                    reason = CASE WHEN ? != '' THEN ? ELSE reason END
                WHERE id = ? AND status = 'pending'
                """,
                (status, approved_by_user_id, signature_hmac, reason, reason, approval_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM workflow_approvals WHERE id = ?", (approval_id,)).fetchone()
            return dict(row) if row is not None else None

    def mark_approval_consumed(self, approval_id: str) -> bool:
        now = utc_now_iso()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE workflow_approvals
                SET status = 'consumed', consumed_at = ?
                WHERE id = ? AND status = 'approved' AND consumed_at IS NULL
                """,
                (now, approval_id),
            )
            return cur.rowcount == 1

    def append_audit_log(
        self,
        *,
        actor_id: str,
        event_type: str,
        resource: str,
        decision: str,
        details: dict[str, Any],
        run_id: str | None = None,
        step_key: str | None = None,
    ) -> str:
        audit_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO workflow_audit_logs (
                    id, run_id, step_key, actor_id, event_type, resource, decision, details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    run_id,
                    step_key,
                    actor_id,
                    event_type,
                    resource,
                    decision,
                    json.dumps(details, ensure_ascii=False),
                    utc_now_iso(),
                ),
            )
            return audit_id

    def list_audit_logs(self, run_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM workflow_audit_logs WHERE run_id = ? ORDER BY created_at DESC LIMIT ?",
                    (run_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM workflow_audit_logs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {
                    **dict(r),
                    "details": self._decode_json(r["details"], {}),
                }
                for r in rows
            ]

    def get_scheduler_last_run(self, workflow_key: str) -> datetime | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT last_triggered_at FROM scheduler_state WHERE workflow_key = ?",
                (workflow_key,),
            ).fetchone()
            if row is None:
                return None
            return datetime.fromisoformat(row["last_triggered_at"])

    def set_scheduler_last_run(self, workflow_key: str, dt: datetime | None = None) -> None:
        ts = (dt or datetime.now(timezone.utc)).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO scheduler_state (workflow_key, last_triggered_at)
                VALUES (?, ?)
                ON CONFLICT(workflow_key) DO UPDATE SET last_triggered_at = excluded.last_triggered_at
                """,
                (workflow_key, ts),
            )
