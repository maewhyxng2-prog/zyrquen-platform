import copy
import unittest

from apps.core.intelligence.plan_contract import (
    ALLOWED_PLAN_STATUS, PlanViolation, analyze_plan, validate_plan)


def _plan(**over):
    p = {
        "goal": "g", "context": {}, "generated_by": "manual",
        "steps": [
            {"id": "a", "description": "da", "depends_on": [],
             "success_criteria": "ca"},
            {"id": "b", "description": "db", "depends_on": ["a"],
             "success_criteria": "cb"},
            {"id": "c", "description": "dc", "depends_on": ["a", "b"],
             "success_criteria": "cc"},
        ],
    }
    p.update(over)
    return p


def _problems(plan):
    r = analyze_plan(plan)
    return r, " | ".join(r["problems"])


class TestPlanContract(unittest.TestCase):
    def test_valid_plan_passes_with_order(self):
        r = analyze_plan(_plan())
        self.assertEqual(r["status"], "valid_structure")
        self.assertEqual(r["step_order"], ["a", "b", "c"])

    def test_rejects_non_dict(self):
        for bad in (None, 5, [], "x"):
            self.assertEqual(analyze_plan(bad)["status"], "invalid_structure")

    def test_rejects_missing_keys(self):
        p = _plan()
        del p["goal"]
        r, txt = _problems(p)
        self.assertEqual(r["status"], "invalid_structure")
        self.assertIn("missing plan keys", txt)

    def test_rejects_empty_steps(self):
        for bad in ([], None, "x"):
            r, _ = _problems(_plan(steps=bad))
            self.assertEqual(r["status"], "invalid_structure")

    def test_rejects_step_missing_fields(self):
        r, _ = _problems(_plan(steps=[{"id": "a"}]))
        self.assertEqual(r["status"], "invalid_structure")

    def test_rejects_missing_success_criteria(self):
        p = _plan()
        p["steps"][0]["success_criteria"] = "  "
        r, txt = _problems(p)
        self.assertEqual(r["status"], "invalid_structure")
        self.assertIn("success_criteria", txt)

    def test_rejects_duplicate_ids(self):
        p = _plan()
        p["steps"][1]["id"] = "a"
        r, txt = _problems(p)
        self.assertIn("duplicate step id", txt)

    def test_rejects_unknown_dependency(self):
        p = _plan()
        p["steps"][1]["depends_on"] = ["zzz"]
        r, txt = _problems(p)
        self.assertIn("unknown", txt)

    def test_rejects_self_dependency(self):
        p = _plan()
        p["steps"][0]["depends_on"] = ["a"]
        r, txt = _problems(p)
        self.assertIn("depends on itself", txt)

    def test_rejects_cycle(self):
        p = _plan()
        p["steps"][0]["depends_on"] = ["c"]
        r, txt = _problems(p)
        self.assertEqual(r["status"], "invalid_structure")
        self.assertIn("cycle", txt)
        self.assertEqual(r["step_order"], [])

    def test_rejects_bad_generated_by(self):
        for bad in ("", "native", None):
            r, _ = _problems(_plan(generated_by=bad))
            self.assertEqual(r["status"], "invalid_structure")

    def test_model_generated_needs_evidence(self):
        p = _plan(generated_by="model_generated")
        for ev in (None, {}, {"model_id": "m"}, {"model_id": "", "response": "x"}):
            self.assertEqual(
                analyze_plan(p, ev)["status"], "invalid_structure")
        ok = analyze_plan(p, {"model_id": "m", "response": "ok"})
        self.assertEqual(ok["status"], "valid_structure")

    def test_validate_plan_raises_and_status_is_closed_set(self):
        with self.assertRaises(PlanViolation):
            validate_plan(_plan(steps=[]))
        validate_plan(_plan())
        for p in (_plan(), _plan(steps=[]), None, copy.deepcopy(_plan())):
            self.assertIn(analyze_plan(p)["status"], ALLOWED_PLAN_STATUS)


if __name__ == "__main__":
    unittest.main()
