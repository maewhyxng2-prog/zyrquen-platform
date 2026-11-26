"""Phase 13 — Knowledge & Data Pipeline — pure logic only.

No training, no real dataset download, no weights, no GPU, no external AI.
Governance + validation only — no record without provenance.
"""
import re
import uuid
from datetime import datetime, timezone

ALLOWED_LICENSES = {"public-domain", "mit", "apache-2.0", "cc-by-4.0", "proprietary-approved"}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LONG_DIGITS_RE = re.compile(r"\d{10,}")

def ingest_record(source, license, attribution, text):
    """Data Ingestion — every record must have provenance."""
    if not source or not str(source).strip():
        raise ValueError("source is required")
    if not license or not str(license).strip():
        raise ValueError("license is required")
    if not attribution or not str(attribution).strip():
        raise ValueError("attribution is required")
    return {
        "id": str(uuid.uuid4()),
        "source": source,
        "license": license,
        "attribution": attribution,
        "text": text or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

def check_governance(record):
    """Dataset Governance — allowed only if license is in allow-list."""
    lic = str(record.get("license", "")).strip().lower()
    if lic in ALLOWED_LICENSES:
        return {"status": "allowed", "reason": ""}
    return {"status": "blocked", "reason": f"license '{lic}' is not in allow-list"}

def validate_record(record, seen_texts=None):
    """Data Validation — returns valid + issues, never fake success."""
    issues = []
    text = str(record.get("text", "") or "")
    if not text.strip():
        issues.append("empty_text")
    elif len(text.strip()) < 10:
        issues.append("too_short")
    if seen_texts is not None and text.strip() in seen_texts:
        issues.append("duplicate")
    if EMAIL_RE.search(text) or LONG_DIGITS_RE.search(text):
        issues.append("possible_pii")
    return {"valid": len(issues) == 0, "issues": issues}
