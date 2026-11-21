"""Phase 16 — Native Reasoning & Planning — pure logic only.

No training, no weights change, no autonomous execution, no external AI.
Default-deny: no approval token = no execution. DAG cycle = blocked.
"""

VALID_KINDS = {"fact", "assumption", "unverified"}

class ReasoningStep:
    def __init__(self, kind, text, evidence=""):
        if kind not in VALID_KINDS:
            raise ValueError(f"invalid kind '{kind}' — must be fact/assumption/unverified")
        self.kind = kind
        self.text = text
        self.evidence = evidence

    def to_dict(self):
        return {"kind": self.kind, "text": self.text, "evidence": self.evidence}

class ReasoningPipeline:
    """Reasoning Architecture — steps with hard cap, no mixing kinds."""

    def __init__(self, max_steps=20):
        self.max_steps = max_steps
        self.steps = []

    def add_step(self, step):
        if len(self.steps) >= self.max_steps:
            return {"status": "blocked", "reason": "step hard cap reached"}
        self.steps.append(step)
        return {"status": "ok", "count": len(self.steps)}

    def summary(self):
        counts = {k: 0 for k in VALID_KINDS}
        for s in self.steps:
            counts[s.kind] += 1
        return {"total": len(self.steps), "by_kind": counts}

def validate_dag(plan):
    """Planning & DAG — cycle or missing dep = invalid / BLOCK."""
    tasks = plan.get("tasks", [])
    ids = set()
    for t in tasks:
        if t.get("id") in ids:
            return {"valid": False, "reason": f"duplicate task id {t.get('id')}"}
        ids.add(t.get("id"))
    for t in tasks:
        for dep in t.get("depends_on", []):
            if dep not in ids:
                return {"valid": False, "reason": f"task {t.get('id')} depends on missing {dep}"}
    # Cycle detection — DFS
    graph = {t.get("id"): t.get("depends_on", []) for t in tasks}
    visiting = set()
    visited = set()

    def dfs(node):
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in graph.get(node, []):
            if dfs(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    for node in ids:
        if dfs(node):
            return {"valid": False, "reason": f"cycle detected at {node}"}
    return {"valid": True, "reason": ""}

class ExecutionSafetyPolicy:
    """Default-deny ExecutionSafetyPolicy — isolated sandbox + approval token."""

    def __init__(self, max_tokens=4000):
        self.max_tokens = max_tokens
        self.tokens_used = 0

    def can_execute(self, action, approval_token=None, sandbox="isolated"):
        if action.get("type") != "execution":
            return {"allowed": True, "reason": "read-only action"}
        if sandbox != "isolated":
            return {"allowed": False, "reason": "execution must be in isolated sandbox"}
        if approval_token != "HUMAN-APPROVED":
            return {"allowed": False, "reason": "missing Human Approval Token — default-deny"}
        tokens = action.get("tokens", 0)
        if self.tokens_used + tokens > self.max_tokens:
            return {"allowed": False, "reason": "token hard cap exceeded"}
        self.tokens_used += tokens
        return {"allowed": True, "reason": "approved"}

def verify_step(step, checker=None):
    """Verification — PASS / FAIL / BLOCKED, never fake PASS."""
    if checker is None:
        return {"status": "BLOCKED", "reason": "no checker provided"}
    try:
        ok = checker(step)
    except Exception as e:
        return {"status": "BLOCKED", "reason": f"checker error: {e}"}
    if ok:
        return {"status": "PASS", "reason": ""}
    return {"status": "FAIL", "reason": "checker returned False"}
