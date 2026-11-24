"""Multi-Source Research Verification & Prompt-Injection Defense.

Enforces:
- SSRF-safe external URL checks for non-AI research tools
- Untrusted source text isolation against prompt injection
- Strict evidence statuses: VERIFIED, SINGLE_SOURCE_UNVERIFIED,
  CONFLICTING_SOURCES, STALE, INSUFFICIENT_EVIDENCE, BLOCKED
- CONFLICTING_SOURCES -> NOT_LEARNED (never written to VerifiedKnowledgeStore)
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .memory_layers import VerifiedKnowledgeStore

EVIDENCE_STATUSES = frozenset({
    "VERIFIED",
    "SINGLE_SOURCE_UNVERIFIED",
    "CONFLICTING_SOURCES",
    "STALE",
    "INSUFFICIENT_EVIDENCE",
    "BLOCKED",
})

_PLACEHOLDER_HOSTS = frozenset({
    "example.com",
    "example.org",
    "example.net",
    "placeholder.invalid",
    "fake.local",
    "test.invalid",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
})

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|system)\s+(?:instructions?|prompts?|rules?)",
            re.IGNORECASE,
        ),
    ),
    (
        "role_hijack",
        re.compile(
            r"(?:you\s+are\s+now|<\|system\|>|<\|developer\|>|override\s+policy|bypass\s+gate)",
            re.IGNORECASE,
        ),
    ),
    (
        "external_llm_redirect",
        re.compile(
            r"(?:call|route\s+to|use)\s+(?:openai|anthropic|claude|gemini|external\s+llm)",
            re.IGNORECASE,
        ),
    ),
    (
        "command_execution_injection",
        re.compile(
            r"(?:execute\s+shell|run\s+bash|rm\s+-rf|curl\s+http://169\.254\.169\.254)",
            re.IGNORECASE,
        ),
    ),
)


def validate_research_url(url: Any) -> dict[str, Any]:
    """Validate an external non-AI research URL and block SSRF / placeholder targets."""
    if not isinstance(url, str) or not url.strip():
        return {"valid": False, "reason": "empty_url"}
    raw = url.strip()
    if any(ch.isspace() or ord(ch) < 32 for ch in raw):
        return {"valid": False, "reason": "control_or_whitespace_in_url"}

    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"https", "http"}:
        return {"valid": False, "reason": f"unsupported_scheme:{parsed.scheme or 'none'}"}
    if parsed.username or parsed.password:
        return {"valid": False, "reason": "credentials_in_url_forbidden"}

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host or "." not in host:
        return {"valid": False, "reason": "invalid_or_single_label_host"}
    if host in _PLACEHOLDER_HOSTS or host.endswith((".invalid", ".example", ".test", ".local", ".internal")):
        return {"valid": False, "reason": f"blocked_or_placeholder_host:{host}"}

    try:
        ip_obj = ipaddress.ip_address(host)
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        ):
            return {"valid": False, "reason": f"ssrf_private_or_reserved_ip:{host}"}
    except ValueError:
        pass

    return {"valid": True, "reason": "ok", "host": host, "scheme": parsed.scheme.lower()}


@dataclass(frozen=True)
class UntrustedEvidenceEnvelope:
    source_id: str
    sanitized_content: str
    raw_sha256: str
    injection_flags: tuple[str, ...]
    compromised: bool
    trust_level: str = "untrusted_data_only"


def sanitize_untrusted_source(text: str, source_id: str) -> UntrustedEvidenceEnvelope:
    """Quarantine prompt-injection attempts in retrieved external content."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    flags: list[str] = []
    cleaned = text.strip()
    for name, pattern in _INJECTION_PATTERNS:
        if pattern.search(cleaned):
            flags.append(name)
            cleaned = pattern.sub("[QUARANTINED_INJECTION_DIRECTIVE]", cleaned)
    return UntrustedEvidenceEnvelope(
        source_id=source_id,
        sanitized_content=cleaned,
        raw_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        injection_flags=tuple(flags),
        compromised=len(flags) > 0,
    )


@dataclass(frozen=True)
class ResearchSource:
    source_id: str
    source_url: str
    retrieved_at: str
    claim_text: str
    polarity: str = "affirms"  # "affirms" | "refutes"
    canonical_value: str | None = None
    credibility_score: float = 0.8
    source_authority: str | None = None


@dataclass(frozen=True)
class ResearchVerificationResult:
    topic: str
    status: str
    learnable: bool
    summary: str
    verified_claim: str | None
    sources_used: tuple[str, ...]
    rejected_sources: dict[str, str] = field(default_factory=dict)
    injection_detected: bool = False
    model_inference: bool = False


class ResearchVerifier:
    """Cross-source verification gate preserving CONFLICTING_SOURCES -> NOT_LEARNED."""

    def __init__(
        self,
        *,
        max_age_hours: float = 24.0 * 30,
        min_credibility: float = 0.5,
    ) -> None:
        self.max_age_hours = max_age_hours
        self.min_credibility = min_credibility

    def _is_fresh(self, retrieved_at: str) -> tuple[bool, str]:
        if not isinstance(retrieved_at, str) or not retrieved_at.strip():
            return False, "missing_timestamp"
        try:
            iso = retrieved_at.strip().replace("Z", "+00:00")
            ts = datetime.fromisoformat(iso)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
            if age_hours < -24.0:
                return False, "future_timestamp"
            if age_hours > self.max_age_hours:
                return False, f"stale_age:{round(age_hours, 1)}h"
            return True, "ok"
        except ValueError:
            return False, "invalid_timestamp"

    def verify_claim(
        self,
        *,
        topic: str,
        sources: list[ResearchSource],
        knowledge_store: VerifiedKnowledgeStore | None = None,
        record_id_prefix: str = "research",
    ) -> ResearchVerificationResult:
        if not sources:
            return ResearchVerificationResult(
                topic=topic,
                status="INSUFFICIENT_EVIDENCE",
                learnable=False,
                summary="No external sources supplied.",
                verified_claim=None,
                sources_used=(),
            )

        valid_entries: list[tuple[ResearchSource, UntrustedEvidenceEnvelope, str]] = []
        rejected: dict[str, str] = {}
        stale_count = 0
        blocked_count = 0
        injection_seen = False

        for src in sources:
            url_check = validate_research_url(src.source_url)
            if not url_check["valid"]:
                rejected[src.source_id] = f"blocked_url:{url_check['reason']}"
                blocked_count += 1
                continue

            if not src.claim_text.strip():
                rejected[src.source_id] = "empty_claim_text"
                continue

            envelope = sanitize_untrusted_source(src.claim_text, src.source_id)
            if envelope.compromised:
                injection_seen = True
                blocked_count += 1
                rejected[src.source_id] = (
                    f"prompt_injection_blocked:{','.join(envelope.injection_flags)}"
                )
                continue

            if src.credibility_score < self.min_credibility:
                rejected[src.source_id] = (
                    f"low_credibility:{src.credibility_score:.2f}"
                )
                continue

            fresh, fresh_reason = self._is_fresh(src.retrieved_at)
            if not fresh:
                stale_count += 1
                rejected[src.source_id] = fresh_reason
                continue

            if src.polarity not in {"affirms", "refutes"}:
                rejected[src.source_id] = f"invalid_polarity:{src.polarity}"
                continue

            authority = (src.source_authority or url_check["host"]).lower()
            valid_entries.append((src, envelope, authority))

        if not valid_entries:
            if blocked_count > 0 and stale_count == 0:
                return ResearchVerificationResult(
                    topic=topic,
                    status="BLOCKED",
                    learnable=False,
                    summary="All supplied sources were blocked by URL/injection security checks.",
                    verified_claim=None,
                    sources_used=(),
                    rejected_sources=rejected,
                    injection_detected=injection_seen,
                )
            if stale_count > 0 and blocked_count == 0:
                return ResearchVerificationResult(
                    topic=topic,
                    status="STALE",
                    learnable=False,
                    summary="All supplied sources are stale past freshness threshold.",
                    verified_claim=None,
                    sources_used=(),
                    rejected_sources=rejected,
                    injection_detected=injection_seen,
                )
            return ResearchVerificationResult(
                topic=topic,
                status="INSUFFICIENT_EVIDENCE",
                learnable=False,
                summary="Insufficient credible fresh sources after validation.",
                verified_claim=None,
                sources_used=(),
                rejected_sources=rejected,
                injection_detected=injection_seen,
            )

        polarities = {src.polarity for src, _, _ in valid_entries}
        values = {
            src.canonical_value.strip().lower()
            for src, _, _ in valid_entries
            if src.canonical_value is not None and src.canonical_value.strip()
        }
        if len(polarities) > 1 or len(values) > 1:
            return ResearchVerificationResult(
                topic=topic,
                status="CONFLICTING_SOURCES",
                learnable=False,
                summary="Conflicting evidence detected across sources; CONFLICTING_SOURCES -> NOT_LEARNED enforced.",
                verified_claim=None,
                sources_used=tuple(src.source_id for src, _, _ in valid_entries),
                rejected_sources=rejected,
                injection_detected=injection_seen,
            )

        independent_authorities = {auth for _, _, auth in valid_entries}
        if len(independent_authorities) < 2:
            return ResearchVerificationResult(
                topic=topic,
                status="SINGLE_SOURCE_UNVERIFIED",
                learnable=False,
                summary="Only one independent authority supports the claim; uncorroborated single source cannot be marked VERIFIED.",
                verified_claim=None,
                sources_used=tuple(src.source_id for src, _, _ in valid_entries),
                rejected_sources=rejected,
                injection_detected=injection_seen,
            )

        lead_src, lead_env, _ = valid_entries[0]
        if knowledge_store is not None:
            knowledge_store.add(
                record_id=f"{record_id_prefix}:{lead_env.raw_sha256[:12]}",
                content=lead_env.sanitized_content,
                source_id=",".join(src.source_id for src, _, _ in valid_entries),
                retrieved_at=lead_src.retrieved_at,
                evidence_status="VERIFIED",
                metadata={
                    "topic": topic,
                    "authorities": sorted(independent_authorities),
                    "polarity": lead_src.polarity,
                },
            )

        return ResearchVerificationResult(
            topic=topic,
            status="VERIFIED",
            learnable=True,
            summary=f"Corroborated across {len(independent_authorities)} independent sources.",
            verified_claim=lead_env.sanitized_content,
            sources_used=tuple(src.source_id for src, _, _ in valid_entries),
            rejected_sources=rejected,
            injection_detected=injection_seen,
        )
