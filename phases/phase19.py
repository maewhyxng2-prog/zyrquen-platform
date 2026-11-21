"""Phase 19 — Autonomous Capability & Safety Governance — pure logic only.

No autonomous execution without approval, no self-escalation,
no unsigned approval token, no training, no weights change,
no external AI, no real deploy.
"""
import hashlib
import hmac
import time

SERVER_SECRET = b"zyrquen-server-secret-v1"

# Tool -> allowed resources. Everything else = default-deny.
ALLOWLIST = {
    "calculator": {"compute"},
    "reader": {"docs"},
    "writer": {"sandbox"},
}

class SafetyGovernance:
    """Tool/Sandbox Boundaries + Server-signed Approval + Human-in-the-loop."""

    def __init__(self):
        self._issued = {}  # token -> approval record
        self._used = set()
        self._counter = 0
        self.audit_log = []

    def check_tool_access(self, tool, resource):
        allowed = resource in ALLOWLIST.get(tool, set())
        return {"status": "allowed" if allowed else "denied", "tool": tool, "resource": resource}

    def issue_approval(self, action, scope, actor="human", ttl_seconds=3600):
        self._counter += 1
        token = f"appr-{self._counter}"
        expires_at = int(time.time()) + int(ttl_seconds)
        payload = f"{token}|{action}|{scope}|{actor}|{expires_at}".encode()
        signature = hmac.new(SERVER_SECRET, payload, hashlib.sha256).hexdigest()
        self._issued[token] = {
            "token": token, "signature": signature, "action": action,
            "scope": scope, "actor": actor, "expires_at": expires_at,
        }
        return {"token": token, "signature": signature, "action": action, "scope": scope, "expires_at": expires_at}

    def verify_approval(self, token, signature, action, scope):
        rec = self._issued.get(token)
        if not rec:
            return {"status": "invalid", "reason": "unknown token"}
        if rec["signature"] != signature:
            return {"status": "invalid", "reason": "bad signature"}
        if rec["action"] != action or rec["scope"] != scope:
            return {"status": "invalid", "reason": "action/scope mismatch"}
        if int(time.time()) > rec["expires_at"]:
            return {"status": "expired", "reason": "token expired"}
        if token in self._used:
            return {"status": "replayed", "reason": "token already used"}
        return {"status": "valid", "token": token}

    def execute_with_approval(self, action, tool, resource, approval_token, approval_signature, actor="human", reason=""):
        # 1) Tool / Sandbox boundary — default-deny
        access = self.check_tool_access(tool, resource)
        if access["status"] != "allowed":
            self.audit_log.append({"action": action, "actor": actor, "approval_id": approval_token, "reason": reason, "result": "blocked-tool-denied", "tool": tool, "resource": resource})
            return {"status": "blocked", "reason": "tool/resource denied"}
        # 2) Server-signed approval — must be valid
        v = self.verify_approval(approval_token, approval_signature, action, resource)
        if v["status"] != "valid":
            self.audit_log.append({"action": action, "actor": actor, "approval_id": approval_token, "reason": reason, "result": f"blocked-{v['status']}", "tool": tool, "resource": resource})
            return {"status": "blocked", "reason": v.get("reason", v["status"])}
        # 3) Human-in-the-loop passed — consume token once, audit it
        self._used.add(approval_token)
        self.audit_log.append({"action": action, "actor": actor, "approval_id": approval_token, "reason": reason, "result": "executed", "tool": tool, "resource": resource})
        return {"status": "ok", "action": action, "tool": tool, "resource": resource}
