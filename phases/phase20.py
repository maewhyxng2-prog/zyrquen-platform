"""Phase 20 — Native Intelligence System Maturity — pure logic only.

No real auto-training, no weight mutation without approval,
no auto-promote, no paid cloud/GPU, no auto production deploy,
no external AI. PASS / FAIL / BLOCKED / NOT RUN are never mixed.
"""

STEPS = ["architecture", "reasoning", "planning", "memory", "learning", "safety"]

class SystemMaturity:
    """End-to-End Integration + Reliability/SLO + Readiness + Maintenance."""

    def run_end_to_end(self, results):
        # results: {step: "PASS"|"FAIL"|"BLOCKED"|"NOT RUN"}
        detail = {}
        for step in STEPS:
            detail[step] = results.get(step, "NOT RUN")
        if "FAIL" in detail.values():
            return {"status": "FAIL", "detail": detail}
        if "BLOCKED" in detail.values():
            return {"status": "BLOCKED", "detail": detail}
        if "NOT RUN" in detail.values():
            return {"status": "NOT RUN", "detail": detail}
        return {"status": "PASS", "detail": detail}

    def evaluate_slo(self, latency_ms, error_rate, recovered):
        ok = latency_ms <= 500 and error_rate <= 0.01 and recovered is True
        return {
            "status": "PASS" if ok else "FAIL",
            "latency_ms": latency_ms,
            "error_rate": error_rate,
            "recovered": recovered,
        }

    def readiness_checklist(self, checks):
        required = ["monitoring", "incident_response", "security", "controls"]
        missing = [k for k in required if not checks.get(k)]
        return {
            "status": "ready" if not missing else "NOT READY",
            "missing": missing,
            "checks": {k: bool(checks.get(k)) for k in required},
        }

    def check_maintenance(self, version_compatible, regression):
        if not version_compatible:
            return {"status": "BLOCKED", "reason": "version incompatible"}
        if regression == "FAIL":
            return {"status": "BLOCKED", "reason": "regression FAIL — no promote"}
        if regression == "NOT RUN":
            return {"status": "NOT RUN", "reason": "regression not run — never counts as PASS"}
        if regression == "PASS":
            return {"status": "ok", "reason": "compatible + regression PASS"}
        return {"status": "BLOCKED", "reason": f"unknown regression status {regression}"}
