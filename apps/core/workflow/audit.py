"""Audit logging and redaction utilities for ZYRQUEN Workflow Engine."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any
from uuid import uuid4

_SENSITIVE_KEYS = frozenset(
    {
        "signature_hmac",
        "hmac",
        "secret",
        "approval_secret",
        "password",
        "password_hash",
        "token",
        "api_key",
        "authorization",
    }
)

_SECRET_PATTERN = re.compile(
    r"(?i)\b(secret|password|passwd|token|api[_-]?key|authorization|hmac|signature_hmac)\b\s*[:=]\s*([^\s,;]+)"
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact_text(value: Any) -> str:
    """Convert value to string and redact inline secret/token assignments."""
    if value is None:
        return ""
    text = str(value)
    return _SECRET_PATTERN.sub(r"\1=[REDACTED]", text)


def redact_dict(value: Any) -> Any:
    """Recursively redact sensitive keys in dicts/lists returned by Workflow APIs."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            kl = str(k).lower()
            if kl in _SENSITIVE_KEYS or any(tok in kl for tok in ("secret", "password", "signature_hmac")):
                out[k] = "[REDACTED]"
            else:
                out[k] = redact_dict(v)
        return out
    if isinstance(value, list):
        return [redact_dict(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class WorkflowAuditLogger:
    """Append-only audit logger backed by WorkflowStore."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def record(
        self,
        *,
        actor_id: str,
        event_type: str,
        resource: str,
        decision: str,
        details: dict[str, Any] | None = None,
        run_id: str | None = None,
        step_key: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        entry = {
            "id": str(uuid4()),
            "run_id": run_id,
            "step_key": step_key,
            "actor_id": redact_text(actor_id or "system"),
            "event_type": str(event_type),
            "resource": redact_text(str(resource)),
            "decision": str(decision),
            "details": redact_dict(details or {}),
            "created_at": created_at or _utc_now_iso(),
        }
        serialized_details = json.dumps(entry["details"], ensure_ascii=False, sort_keys=True)

        if hasattr(self.store, "append_audit_log"):
            self.store.append_audit_log(
                entry_id=entry["id"],
                run_id=entry["run_id"],
                step_key=entry["step_key"],
                actor_id=entry["actor_id"],
                event_type=entry["event_type"],
                resource=entry["resource"],
                decision=entry["decision"],
                details_json=serialized_details,
                created_at=entry["created_at"],
            )
            return entry

        conn = getattr(self.store, "conn", None) or getattr(self.store, "_conn", None)
        if conn is not None:
            conn.execute(
                """
                INSERT INTO workflow_audit_logs (
                    id, run_id, step_key, actor_id, event_type, resource, decision, details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry["id"],
                    entry["run_id"],
                    entry["step_key"],
                    entry["actor_id"],
                    entry["event_type"],
                    entry["resource"],
                    entry["decision"],
                    serialized_details,
                    entry["created_at"],
                ),
            )
            if hasattr(conn, "commit"):
                conn.commit()
        return entry
