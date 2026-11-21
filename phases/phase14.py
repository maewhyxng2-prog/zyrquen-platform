"""Phase 14 — Evaluation & Capability Measurement — pure logic only.

No training, no dataset, no weights, no GPU, no external AI.
NOT RUN is never PASS. Every result has evidence + reason.
"""

VALID_STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT RUN"}

def evaluate_case(case):
    """Evaluation Framework — return PASS / FAIL / BLOCKED / NOT RUN."""
    name = case.get("name", "unnamed")
    evidence = case.get("evidence", "")
    reason = case.get("reason", "")
    if not case.get("ran", False):
        return {"name": name, "status": "NOT RUN", "evidence": evidence, "reason": reason or "not run"}
    if case.get("blocked", False):
        return {"name": name, "status": "BLOCKED", "evidence": evidence, "reason": reason or "blocked"}
    if case.get("passed", False):
        return {"name": name, "status": "PASS", "evidence": evidence, "reason": reason or "passed"}
    return {"name": name, "status": "FAIL", "evidence": evidence, "reason": reason or "failed"}

def compare_benchmark(prev, curr):
    """Benchmark & Regression — higher is better. curr < prev = regression."""
    diff = {}
    regression = False
    for key in set(prev) | set(curr):
        p = prev.get(key)
        c = curr.get(key)
        if p is None or c is None:
            diff[key] = {"prev": p, "curr": c, "delta": None}
            continue
        delta = c - p
        diff[key] = {"prev": p, "curr": c, "delta": delta}
        if delta < 0:
            regression = True
    return {"regression": regression, "diff": diff}

def reliability_score(results):
    """Reliability — PASS / (PASS + FAIL) only. BLOCKED / NOT RUN excluded."""
    passed = sum(1 for r in results if r.get("status") == "PASS")
    failed = sum(1 for r in results if r.get("status") == "FAIL")
    total = passed + failed
    if total == 0:
        return 0.0
    return passed / total

def regression_gate(prev, curr):
    """Regression Gate — block acceptance if regression is True."""
    cmp = compare_benchmark(prev, curr)
    if cmp["regression"]:
        return {"allowed": False, "reason": "regression detected", "diff": cmp["diff"]}
    return {"allowed": True, "reason": "no regression", "diff": cmp["diff"]}
