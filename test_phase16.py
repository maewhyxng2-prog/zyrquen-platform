import pytest
from phase16 import (
    ExecutionSafetyPolicy,
    ReasoningPipeline,
    ReasoningStep,
    validate_dag,
    verify_step,
)

def test_reasoning_step_kinds_and_pipeline():
    p = ReasoningPipeline(max_steps=5)
    p.add_step(ReasoningStep("fact", "2+2=4", evidence="math"))
    p.add_step(ReasoningStep("assumption", "ผู้ใช้น่าจะต้องการสรุป"))
    p.add_step(ReasoningStep("unverified", "ผลนี้ยังไม่ได้ตรวจ"))
    s = p.summary()
    assert s["total"] == 3
    assert s["by_kind"]["fact"] == 1
    assert s["by_kind"]["assumption"] == 1
    with pytest.raises(ValueError):
        ReasoningStep("magic", "x")

def test_pipeline_hard_cap_blocks():
    p = ReasoningPipeline(max_steps=2)
    p.add_step(ReasoningStep("fact", "a"))
    p.add_step(ReasoningStep("fact", "b"))
    out = p.add_step(ReasoningStep("fact", "c"))
    assert out["status"] == "blocked"

def test_dag_valid():
    plan = {"tasks": [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": ["a"]},
        {"id": "c", "depends_on": ["b"]},
    ]}
    assert validate_dag(plan)["valid"] is True

def test_dag_cycle_and_missing_blocked():
    cycle = {"tasks": [
        {"id": "a", "depends_on": ["b"]},
        {"id": "b", "depends_on": ["a"]},
    ]}
    assert validate_dag(cycle)["valid"] is False
    missing = {"tasks": [{"id": "a", "depends_on": ["ghost"]}]}
    assert validate_dag(missing)["valid"] is False

def test_execution_default_deny_without_token():
    pol = ExecutionSafetyPolicy()
    # No token = blocked
    out = pol.can_execute({"type": "execution", "tokens": 10}, approval_token=None)
    assert out["allowed"] is False
    # Wrong sandbox = blocked even with token
    out2 = pol.can_execute({"type": "execution", "tokens": 10}, approval_token="HUMAN-APPROVED", sandbox="host")
    assert out2["allowed"] is False
    # Correct token + isolated sandbox = allowed
    out3 = pol.can_execute({"type": "execution", "tokens": 10}, approval_token="HUMAN-APPROVED", sandbox="isolated")
    assert out3["allowed"] is True
    # Read-only = allowed without token
    assert pol.can_execute({"type": "read"})["allowed"] is True

def test_verification_pass_fail_blocked():
    step = ReasoningStep("fact", "2+2=4")
    assert verify_step(step, checker=lambda s: True)["status"] == "PASS"
    assert verify_step(step, checker=lambda s: False)["status"] == "FAIL"
    assert verify_step(step, checker=None)["status"] == "BLOCKED"
