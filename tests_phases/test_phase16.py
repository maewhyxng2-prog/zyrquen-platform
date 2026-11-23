import unittest
from phases.phase16 import (
    ExecutionSafetyPolicy,
    ReasoningPipeline,
    ReasoningStep,
    validate_dag,
    verify_step,
)


class TestPhase16(unittest.TestCase):
    def test_reasoning_step_kinds_and_pipeline(self):
        p = ReasoningPipeline(max_steps=5)
        p.add_step(ReasoningStep("fact", "2+2=4", evidence="math"))
        p.add_step(ReasoningStep("assumption", "ผู้ใช้น่าจะต้องการสรุป"))
        p.add_step(ReasoningStep("unverified", "ผลนี้ยังไม่ได้ตรวจ"))
        s = p.summary()
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["by_kind"]["fact"], 1)
        self.assertEqual(s["by_kind"]["assumption"], 1)
        with self.assertRaises(ValueError):
            ReasoningStep("magic", "x")

    def test_pipeline_hard_cap_blocks(self):
        p = ReasoningPipeline(max_steps=2)
        p.add_step(ReasoningStep("fact", "a"))
        p.add_step(ReasoningStep("fact", "b"))
        out = p.add_step(ReasoningStep("fact", "c"))
        self.assertEqual(out["status"], "blocked")

    def test_dag_valid(self):
        plan = {"tasks": [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["b"]},
        ]}
        self.assertIs(validate_dag(plan)["valid"], True)

    def test_dag_cycle_and_missing_blocked(self):
        cycle = {"tasks": [
            {"id": "a", "depends_on": ["b"]},
            {"id": "b", "depends_on": ["a"]},
        ]}
        self.assertIs(validate_dag(cycle)["valid"], False)
        missing = {"tasks": [{"id": "a", "depends_on": ["ghost"]}]}
        self.assertIs(validate_dag(missing)["valid"], False)

    def test_execution_default_deny_without_token(self):
        pol = ExecutionSafetyPolicy()
        # No token = blocked
        out = pol.can_execute({"type": "execution", "tokens": 10}, approval_token=None)
        self.assertIs(out["allowed"], False)
        # Wrong sandbox = blocked even with token
        out2 = pol.can_execute({"type": "execution", "tokens": 10}, approval_token="HUMAN-APPROVED", sandbox="host")
        self.assertIs(out2["allowed"], False)
        # Correct token + isolated sandbox = allowed
        out3 = pol.can_execute({"type": "execution", "tokens": 10}, approval_token="HUMAN-APPROVED", sandbox="isolated")
        self.assertIs(out3["allowed"], True)
        # Read-only = allowed without token
        self.assertIs(pol.can_execute({"type": "read"})["allowed"], True)

    def test_verification_pass_fail_blocked(self):
        step = ReasoningStep("fact", "2+2=4")
        self.assertEqual(verify_step(step, checker=lambda s: True)["status"], "PASS")
        self.assertEqual(verify_step(step, checker=lambda s: False)["status"], "FAIL")
        self.assertEqual(verify_step(step, checker=None)["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
