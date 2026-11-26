import unittest
from unittest import mock

from apps.core.intelligence import KnowledgeSystem, ReasoningEngine
from apps.core.intelligence import reasoning as reasoning_mod
from apps.core.intelligence.contract import ContractViolation, validate_result


def _engine(with_relation):
    ks = KnowledgeSystem()
    ks.add_entity("zyrquen", {"type": "AI"})
    if with_relation:
        ks.add_entity("phase_9", {"name": "N"})
        ks.add_relation("zyrquen", "phase_9")
    return ReasoningEngine(ks)


def _bad(**over):
    r = {
        "context": "c", "question": "q", "related_knowledge_found": True,
        "reasoning_path": ["x"], "status": "lookup_only",
        "engine_type": "rule_based_scaffold", "model_inference": False,
    }
    r.update(over)
    return r


def _raw(result):
    return mock.patch.object(
        ReasoningEngine, "_deduce_unvalidated", return_value=result)


class TestRuntimeEnforcement(unittest.TestCase):
    def test_lookup_path_passes(self):
        r = _engine(True).deduce(context="zyrquen", question="q")
        self.assertEqual(r["status"], "lookup_only")

    def test_no_knowledge_path_passes(self):
        r = _engine(False).deduce(context="zyrquen", question="q")
        self.assertEqual(r["status"], "no_knowledge_found")

    def test_rejects_unknown_status(self):
        with _raw(_bad(status="reasoning_complete")):
            with self.assertRaises(ContractViolation):
                _engine(True).deduce(context="zyrquen", question="q")

    def test_rejects_inconsistent_status(self):
        with _raw(_bad(related_knowledge_found=False)):
            with self.assertRaises(ContractViolation):
                _engine(True).deduce(context="zyrquen", question="q")

    def test_rejects_unproven_model_inference(self):
        with _raw(_bad(model_inference=True)):
            with self.assertRaises(ContractViolation):
                _engine(True).deduce(context="zyrquen", question="q")

    def test_rejects_missing_key(self):
        r = _bad()
        del r["engine_type"]
        with _raw(r):
            with self.assertRaises(ContractViolation):
                _engine(True).deduce(context="zyrquen", question="q")

    def test_validator_runs_on_every_call(self):
        with mock.patch.object(reasoning_mod, "validate_result",
                               wraps=validate_result) as spy:
            _engine(True).deduce(context="zyrquen", question="q")
            _engine(False).deduce(context="zyrquen", question="q")
        self.assertEqual(spy.call_count, 2)


if __name__ == "__main__":
    unittest.main()
