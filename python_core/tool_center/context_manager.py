"""
Context Manager for ZYRQUEN Tool Center.
----------------------------------------
Builds minimal, schema-scoped, secret-redacted input contexts for capability
executions instead of passing unbounded workspace or conversation dumps.
Tracks byte footprint and pruned/redacted keys for full observability.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .contracts import CapabilitySpec

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bghp_[0-9A-Za-z]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END .*?PRIVATE KEY-----"),
)

_SENSITIVE_META_KEYS = frozenset({
    "password",
    "password_hash",
    "token",
    "api_key",
    "secret",
    "authorization",
    "cookie",
    "private_key",
})


def _redact_string(val: str) -> tuple[str, int]:
    redactions = 0
    out = val
    for pat in _SECRET_PATTERNS:
        out, n = pat.subn("[REDACTED_SECRET]", out)
        redactions += n
    return out, redactions


def _sanitize_value(val: Any, *, max_str_len: int = 24_000) -> tuple[Any, int]:
    if isinstance(val, str):
        red, count = _redact_string(val)
        if len(red) > max_str_len:
            red = red[:max_str_len] + "...[truncated]"
        return red, count
    if isinstance(val, list):
        out_list = []
        total_red = 0
        for item in val[:200]:
            cleaned, c = _sanitize_value(item, max_str_len=max_str_len)
            out_list.append(cleaned)
            total_red += c
        return out_list, total_red
    if isinstance(val, dict):
        out_dict: dict[str, Any] = {}
        total_red = 0
        for k, v in val.items():
            kl = str(k).lower()
            if kl in _SENSITIVE_META_KEYS:
                out_dict[k] = "[REDACTED]"
                total_red += 1
            else:
                cleaned, c = _sanitize_value(v, max_str_len=max_str_len)
                out_dict[k] = cleaned
                total_red += c
        return out_dict, total_red
    return val, 0


class ContextManager:
    """Extracts minimal schema-relevant payload and safe execution metadata for a capability."""

    def __init__(self, *, max_payload_bytes: int = 65_536) -> None:
        self.max_payload_bytes = max_payload_bytes

    def build_scoped_input(
        self,
        spec: CapabilitySpec,
        raw_input: dict[str, Any] | None,
        *,
        shared_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Select only keys relevant to `spec.input_schema`, merge minimal missing defaults
        from `shared_context` (never dumping full context blobs), strip secrets, and
        measure context footprint.
        """
        raw = dict(raw_input) if isinstance(raw_input, dict) else {}
        ctx = dict(shared_context) if isinstance(shared_context, dict) else {}
        props = dict((spec.input_schema or {}).get("properties") or {})
        allowed_keys = set(props.keys())

        scoped: dict[str, Any] = {}
        pruned_keys: list[str] = []
        injected_from_context: list[str] = []
        redacted_count = 0

        # Keep declared schema keys from explicit input first
        for key, val in raw.items():
            if allowed_keys and key not in allowed_keys:
                pruned_keys.append(key)
                continue
            cleaned, red = _sanitize_value(val)
            scoped[key] = cleaned
            redacted_count += red

        # Fill missing required/declared keys only from matching keys in shared_context
        for key in allowed_keys:
            if key in scoped and scoped[key] is not None:
                continue
            if key in ctx and ctx[key] is not None:
                cleaned, red = _sanitize_value(ctx[key])
                scoped[key] = cleaned
                redacted_count += red
                injected_from_context.append(key)

        # Safe fallback mapping between goal <-> query only when declared by capability schema
        if "goal" in allowed_keys and "goal" not in scoped and ctx.get("goal"):
            cleaned, red = _sanitize_value(ctx["goal"], max_str_len=2000)
            scoped["goal"] = cleaned
            redacted_count += red
            injected_from_context.append("goal")
        if "query" in allowed_keys and "query" not in scoped and (ctx.get("query") or ctx.get("goal")):
            cleaned, red = _sanitize_value(ctx.get("query") or ctx.get("goal"), max_str_len=1000)
            scoped["query"] = cleaned
            redacted_count += red
            injected_from_context.append("query")

        encoded_bytes = len(json.dumps(scoped, ensure_ascii=False).encode("utf-8"))
        truncated_oversize = False
        if encoded_bytes > self.max_payload_bytes:
            truncated_oversize = True
            for k, v in list(scoped.items()):
                if isinstance(v, str) and len(v) > 8000:
                    scoped[k] = v[:8000] + "...[trimmed_to_budget]"
            encoded_bytes = len(json.dumps(scoped, ensure_ascii=False).encode("utf-8"))

        return {
            "scoped_input": scoped,
            "footprint": {
                "capability_id": spec.id,
                "original_input_keys": sorted(raw.keys()),
                "scoped_keys": sorted(scoped.keys()),
                "pruned_keys": sorted(pruned_keys),
                "injected_from_context": sorted(set(injected_from_context)),
                "redacted_count": redacted_count,
                "payload_bytes": encoded_bytes,
                "truncated_oversize": truncated_oversize,
            },
        }
