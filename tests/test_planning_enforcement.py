import copy
import unittest
from unittest import mock

from apps.core.intelligence import planning as planning_mod
from apps.core.intelligence.plan_contract import (
    ALLOWED_PLAN_STATUS, PlanViolation, validate_plan)
from apps.core.intelligence.planning import PlanningEngine


def _steps():
    return [
        {"id": "a", "description": "da", "depends_on": [],
         "success_criteria": "ca"},
        {"id": "b", "description": "db", "depends_on": ["a"],
         "success_criteria": "cb"},
    ]


def _build(**over):
    kw = {"goal": "g", "context": {"k": "v"}, "steps": _steps()}
    kw.update(over)
    return PlanningEngine().build_plan(**kw)


class TestPlanningEnforcement(unittest.TestCase):
    def test_valid_manual_plan_result(self):
        r = _build()
        self.assertEqual(r["status"], "valid_structure")
        self.assertEqual(r["step_order"], ["a", "b"])
        self.assertEqual(r["engine_type"], "plan_validator")
        self.assertIs(r["model_inference"], False)
        self.assertEqual(r["generated_by"], "manual")

    def test_rule_based_allowed(self):
        r = _build(generated_by="rule_based")
        self.assertEqual(r["status"], "valid_structure")

    def test_rejects_invalid_structures(self):
        cycle = _steps()
        cycle[0]["depends_on"] = ["b"]
        no_crit = _steps()
        no_crit[0]["success_criteria"] = ""
        unknown = _steps()
        unknown[1]["depends_on"] = ["zzz"]
        cases = {"empty": [], "cycle": cycle, "no_criteria": no_crit,
                 "unknown_dep": unknown, "not_list": "x"}
        for name, bad in cases.items():
            with self.subTest(name):
                with self.assertRaises(PlanViolation):
                    _build(steps=bad)

    def test_rejects_bad_generated_by(self):
        for bad in ("native", "", None):
            with self.subTest(bad):
                with self.assertRaises(PlanViolation):
                    _build(generated_by=bad)

    def test_model_generated_rejected_without_evidence(self):
        for ev in (None, {}, {"model_id": "m"}):
            with self.subTest(ev):
                with self.assertRaises(PlanViolation):
                    _build(generated_by="model_generated",
                           native_model_evidence=ev)

    def test_model_generated_with_evidence_still_not_inference(self):
        r = _build(generated_by="model_generated",
                   native_model_evidence={"model_id": "m", "response": "ok"})
        self.assertEqual(r["status"], "valid_structure")
        self.assertIs(r["model_inference"], False)

    def test_does_not_mutate_inputs(self):
        steps = _steps()
        ctx = {"k": ["v"]}
        before = (copy.deepcopy(steps), copy.deepcopy(ctx))
        r = _build(steps=steps, context=ctx)
        r["steps"][0]["id"] = "changed"
        r["context"]["k"].append("x")
        self.assertEqual((steps, ctx), before)

    def test_validator_runs_every_call(self):
        with mock.patch.object(planning_mod, "validate_plan",
                               wraps=validate_plan) as spy:
            _build()
            with self.assertRaises(PlanViolation):
                _build(steps=[])
        self.assertEqual(spy.call_count, 2)

    def test_result_keys_and_closed_status(self):
        r = _build()
        self.assertEqual(set(r), {
            "goal", "context", "steps", "generated_by", "status",
            "step_order", "engine_type", "model_inference"})
        self.assertIn(r["status"], ALLOWED_PLAN_STATUS)


if __name__ == "__main__":
    unittest.main()
