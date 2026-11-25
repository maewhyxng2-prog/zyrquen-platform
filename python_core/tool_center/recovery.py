"""
Failure Recovery Engine & Resumable Orchestration State for ZYRQUEN Tool Center.
--------------------------------------------------------------------------------
Implements:
  - Explicit Error Taxonomy (INVALID_INPUT, PERMISSION_BLOCKED, DEPENDENCY_MISSING,
    VERSION_CONFLICT, TIMEOUT, RESOURCE_LIMIT, TRANSIENT_ERROR, CONTRACT_MISMATCH,
    QA_FAILED, EXECUTION_ERROR)
  - Idempotent bounded retry policy for transient/timeout failures
  - Safe fallback resolution (never mutates code or bypasses P5 gates)
  - Resumable SQLite persistence (`orchestration_runs`, `orchestration_steps`)
    with idempotency keys to prevent unintended duplicate execution.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from typing import Any

ERROR_TAXONOMY = frozenset({
    "INVALID_INPUT",
    "PERMISSION_BLOCKED",
    "DEPENDENCY_MISSING",
    "VERSION_CONFLICT",
    "TIMEOUT",
    "RESOURCE_LIMIT",
    "TRANSIENT_ERROR",
    "CONTRACT_MISMATCH",
    "QA_FAILED",
    "EXECUTION_ERROR",
})

_RETRYABLE_ERRORS = frozenset({"TRANSIENT_ERROR", "TIMEOUT"})


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def init_orchestration_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS orchestration_runs (
            id TEXT PRIMARY KEY,
            idempotency_key TEXT UNIQUE,
            goal TEXT NOT NULL,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('RUNNING', 'SUCCESS', 'PARTIAL_SUCCESS', 'FAILED', 'UNVERIFIED', 'PENDING_APPROVAL')),
            plan_json TEXT NOT NULL,
            context_summary_json TEXT NOT NULL DEFAULT '{}',
            qa_summary_json TEXT NOT NULL DEFAULT '{}',
            recovery_events_json TEXT NOT NULL DEFAULT '[]',
            total_latency_ms REAL NOT NULL DEFAULT 0.0,
            external_models_used INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS orchestration_steps (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            capability_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('SUCCESS', 'PARTIAL_SUCCESS', 'FAILED', 'UNVERIFIED', 'PENDING_APPROVAL', 'BLOCKED')),
            attempts INTEGER NOT NULL DEFAULT 1,
            error_code TEXT,
            error_message TEXT,
            recovery_action TEXT,
            context_footprint_json TEXT NOT NULL DEFAULT '{}',
            output_json TEXT NOT NULL DEFAULT '{}',
            qa_json TEXT NOT NULL DEFAULT '{}',
            latency_ms REAL NOT NULL DEFAULT 0.0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES orchestration_runs(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_orch_runs_created
            ON orchestration_runs (created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_orch_steps_idem
            ON orchestration_steps (idempotency_key, status);
        """
    )


def build_step_idempotency_key(scope: str, step_id: str, capability_id: str, input_payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {
            "scope": scope,
            "step_id": step_id,
            "capability_id": capability_id,
            "input": input_payload,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def classify_error(result: dict[str, Any] | None, *, default_msg: str = "") -> tuple[str, str]:
    if not result:
        return "EXECUTION_ERROR", default_msg or "Empty execution result"
    if result.get("error_code") in ERROR_TAXONOMY:
        return str(result["error_code"]), str(result.get("error") or default_msg or "Execution error")

    status = str(result.get("status") or "").upper()
    err = str(result.get("error") or default_msg or "").strip()
    lower = err.lower()

    if "timeout" in lower or "exceeded" in lower and "timeout" in lower:
        return "TIMEOUT", err
    if "resource_limit" in lower or "ram" in lower and "threshold" in lower or "concurrent workload" in lower:
        return "RESOURCE_LIMIT", err
    if "missing required input" in lower or "must be of type" in lower or "must be a json" in lower:
        return "INVALID_INPUT", err
    if "missing dependencies" in lower or "not registered" in lower:
        return "DEPENDENCY_MISSING", err
    if "version" in lower and "conflict" in lower:
        return "VERSION_CONFLICT", err
    if "output of" in lower and "missing declared contract" in lower:
        return "CONTRACT_MISMATCH", err
    if status == "BLOCKED" or "permission" in lower or "admin role" in lower or "in_development" in lower or "forbidden" in lower:
        return "PERMISSION_BLOCKED", err
    if any(tok in lower for tok in ("temporarily", "connection reset", "timed out", "http 503", "http 429", "urlerror")):
        return "TRANSIENT_ERROR", err
    return "EXECUTION_ERROR", err or f"Execution returned status={status or 'FAILED'}"


def recommend_recovery(
    error_code: str,
    *,
    capability_id: str,
    attempt: int,
    max_attempts: int,
    registry: Any,
    fallback_candidates: list[str] | None = None,
) -> dict[str, Any]:
    """
    Decide safe recovery action:
      - Retry with small bounded backoff for TRANSIENT_ERROR / TIMEOUT if attempts remain
      - Otherwise try an explicitly READY compatible fallback capability if available
      - Never bypasses PERMISSION_BLOCKED, INVALID_INPUT, or P5 Approval Gate
    """
    if error_code in _RETRYABLE_ERRORS and attempt < max_attempts:
        return {
            "strategy": "retry",
            "reason": f"Transient failure '{error_code}' on attempt {attempt}/{max_attempts}; retrying idempotently.",
            "backoff_s": min(0.25, 0.05 * attempt),
        }

    if error_code in {"EXECUTION_ERROR", "TRANSIENT_ERROR", "TIMEOUT", "DEPENDENCY_MISSING"} and fallback_candidates:
        for alt_id in fallback_candidates:
            if alt_id == capability_id:
                continue
            spec = registry.get_spec(alt_id)
            if spec and spec.lifecycle_status == "READY" and spec.permission_mode == "auto":
                return {
                    "strategy": "fallback_capability",
                    "fallback_capability_id": alt_id,
                    "reason": f"Switched safely to READY fallback capability '{alt_id}' after '{error_code}'.",
                }

    return {
        "strategy": "halt",
        "reason": f"No safe automatic recovery for '{error_code}' on '{capability_id}'.",
    }
