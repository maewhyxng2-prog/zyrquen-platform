import unittest

from apps.core.intelligence import KnowledgeSystem, ReasoningEngine
from apps.core.intelligence.contract import ContractViolation, validate_result


def _good(**over):
    r = {
        "context": "c", "question": "q", "related_knowledge_found": True,
        "reasoning_path": ["x"], "status": "lookup_only",
        "engine_type": "rule_based_scaffold", "model_inference": False,
    }
    r.update(over)
    return r


class TestContract(unittest.TestCase):
    def test_real_lookup_passes(self):
        ks = KnowledgeSystem()
        ks.add_entity("zyrquen", {"type": "AI"})
        ks.add_entity("phase_9", {"name": "N"})
        ks.add_relation("zyrquen", "phase_9")
        validate_result(ReasoningEngine(ks).deduce(context="zyrquen", question="q"))

    def test_real_no_knowledge_passes(self):
        ks = KnowledgeSystem()
        ks.add_entity("zyrquen", {"type": "AI"})
        validate_result(ReasoningEngine(ks).deduce(context="zyrquen", question="q"))

    def test_rejects_unknown_status(self):
        for bad in ("reasoning_complete", "", None):
            with self.assertRaises(ContractViolation):
                validate_result(_good(status=bad))

    def test_rejects_missing_key(self):
        r = _good()
        del r["engine_type"]
        with self.assertRaises(ContractViolation):
            validate_result(r)

    def test_rejects_inconsistent_status(self):
        with self.assertRaises(ContractViolation):
            validate_result(_good(related_knowledge_found=False))

    def test_model_inference_true_needs_evidence(self):
        r = _good(model_inference=True)
        for ev in (None, {}, {"model_id": "m"}, {"model_id": "", "response": "x"}):
            with self.assertRaises(ContractViolation):
                validate_result(r, native_model_evidence=ev)
        validate_result(r, native_model_evidence={"model_id": "m", "response": "ok"})

    def test_model_inference_must_be_bool(self):
        with self.assertRaises(ContractViolation):
            validate_result(_good(model_inference="false"))


if __name__ == "__main__":
    unittest.main()
