"""Append-only workflow audit logging with automatic sensitive text redaction."""

from __future__ import annotations

import re
from typing import Any

from apps.core.workflow.store import WorkflowStore

SENSITIVE_KEYWORDS = (
    "authorization",
    "password",
    "passwd",
    "token",
    "api_key",
    "apikey",
    "cookie",
    "secret",
    "signature",
)

_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._\-+/=]+", re.IGNORECASE)


def redact_text(value: Any) -> str:
    text = _BEARER_RE.sub("Bearer [REDACTED]", str(value))
    for kw in SENSITIVE_KEYWORDS:
        text = re.sub(re.escape(kw), "[REDACTED]", text, flags=re.IGNORECASE)
    return text


def redact_dict(data: Any) -> Any:
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for k, v in data.items():
            kl = str(k).lower()
            if any(s in kl for s in SENSITIVE_KEYWORDS):
                out[str(k)] = "[REDACTED]"
            else:
                out[str(k)] = redact_dict(v)
        return out
    if isinstance(data, list):
        return [redact_dict(item) for item in data]
    if isinstance(data, str):
        return redact_text(data)
    return data


class WorkflowAuditLogger:
    def __init__(self, store: WorkflowStore) -> None:
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
    ) -> str:
        safe_details = redact_dict(details or {})
        return self.store.append_audit_log(
            actor_id=redact_text(actor_id),
            event_type=redact_text(event_type),
            resource=redact_text(resource),
            decision=redact_text(decision),
            details=safe_details if isinstance(safe_details, dict) else {"value": safe_details},
            run_id=run_id,
            step_key=step_key,
        )
