"""Audit redaction utilities for ZYRQUEN Workflow Engine (pure Python stdlib)."""

from __future__ import annotations

from typing import Any

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
    return value
