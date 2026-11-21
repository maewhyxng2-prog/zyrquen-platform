from phase19 import SafetyGovernance

def test_tool_sandbox_allowed():
    g = SafetyGovernance()
    assert g.check_tool_access("reader", "docs")["status"] == "allowed"
    assert g.check_tool_access("writer", "sandbox")["status"] == "allowed"

def test_tool_sandbox_default_deny():
    g = SafetyGovernance()
    assert g.check_tool_access("reader", "system")["status"] == "denied"
    assert g.check_tool_access("unknown-tool", "docs")["status"] == "denied"
    assert g.check_tool_access("writer", "production")["status"] == "denied"

def test_server_signed_approval_valid():
    g = SafetyGovernance()
    ap = g.issue_approval("read", "docs")
    out = g.verify_approval(ap["token"], ap["signature"], "read", "docs")
    assert out["status"] == "valid"

def test_server_signed_approval_replay_and_tamper_blocked():
    g = SafetyGovernance()
    ap = g.issue_approval("read", "docs")
    # Tampered signature
    assert g.verify_approval(ap["token"], "0" * 64, "read", "docs")["status"] == "invalid"
    # Wrong scope
    assert g.verify_approval(ap["token"], ap["signature"], "read", "system")["status"] == "invalid"
    # Expired
    ap2 = g.issue_approval("read", "docs", ttl_seconds=-1)
    assert g.verify_approval(ap2["token"], ap2["signature"], "read", "docs")["status"] == "expired"
    # Replay — use once via execute, second use must be replayed
    ap3 = g.issue_approval("read", "docs")
    assert g.execute_with_approval("read", "reader", "docs", ap3["token"], ap3["signature"], reason="test")["status"] == "ok"
    assert g.verify_approval(ap3["token"], ap3["signature"], "read", "docs")["status"] == "replayed"

def test_human_in_loop_blocks_without_approval():
    g = SafetyGovernance()
    out = g.execute_with_approval("read", "reader", "docs", "fake", "fake", reason="no approval")
    assert out["status"] == "blocked"
    # Tool denied also blocks even with valid approval
    ap = g.issue_approval("read", "system")
    out2 = g.execute_with_approval("read", "reader", "system", ap["token"], ap["signature"], reason="out of scope")
    assert out2["status"] == "blocked"

def test_human_in_loop_audit_log():
    g = SafetyGovernance()
    ap = g.issue_approval("read", "docs")
    g.execute_with_approval("read", "reader", "docs", ap["token"], ap["signature"], actor="human", reason="user requested")
    assert len(g.audit_log) == 1
    entry = g.audit_log[0]
    assert entry["result"] == "executed"
    assert entry["approval_id"] == ap["token"]
    assert entry["reason"] == "user requested"
