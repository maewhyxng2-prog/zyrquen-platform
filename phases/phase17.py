"""Phase 17 — Memory & Knowledge Integration — pure logic only.

No training, no weights change, no dataset download, no external AI.
Every memory has owner_id + workspace_id + source. No cross-tenant recall.
"""
import re

TIERS = {"short", "long", "task"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

class MemoryStore:
    """Tiered Memory + Grounded Retrieval + Multi-tenant Integrity."""

    def __init__(self):
        self._store = {t: {} for t in TIERS}

    def store(self, tier, key, value, owner_id, workspace_id, source="", verified=False):
        if tier not in TIERS:
            return {"status": "blocked", "reason": f"invalid tier '{tier}'"}
        if not owner_id or not workspace_id:
            return {"status": "blocked", "reason": "owner_id and workspace_id are required"}
        if not value or not str(value).strip():
            return {"status": "blocked", "reason": "empty value"}
        if EMAIL_RE.search(str(value)):
            return {"status": "blocked", "reason": "possible PII — not stored"}
        self._store[tier][key] = {
            "value": value,
            "owner_id": owner_id,
            "workspace_id": workspace_id,
            "source": source,
            "verified": bool(verified),
        }
        return {"status": "ok", "tier": tier, "key": key}

    def recall(self, tier, key, owner_id, workspace_id):
        if tier not in TIERS:
            return {"status": "blocked", "reason": f"invalid tier '{tier}'", "result": None}
        entry = self._store[tier].get(key)
        if not entry:
            return {"status": "not_found", "reason": "key not found", "result": None}
        if entry["owner_id"] != owner_id or entry["workspace_id"] != workspace_id:
            return {"status": "blocked", "reason": "cross-tenant recall blocked", "result": None}
        return {"status": "ok", "result": entry["value"], "source": entry["source"], "verified": entry["verified"]}

    def retrieve(self, query, owner_id, workspace_id):
        """Grounded Retrieval — only results with source, only own tenant."""
        q = (query or "").strip().lower()
        if not q:
            return []
        out = []
        for tier in TIERS:
            for key, entry in self._store[tier].items():
                if entry["owner_id"] != owner_id or entry["workspace_id"] != workspace_id:
                    continue
                if not entry.get("source"):
                    continue
                text = str(entry["value"]).lower()
                if q in text or q in key.lower():
                    out.append({
                        "text": entry["value"],
                        "source": entry["source"],
                        "verified": entry["verified"],
                        "tier": tier,
                        "key": key,
                    })
        return out
