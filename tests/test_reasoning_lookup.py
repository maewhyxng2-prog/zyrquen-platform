import unittest

from apps.core.intelligence import KnowledgeSystem, ReasoningEngine


class TestReasoningLookup(unittest.TestCase):
    def test_lookup_only_when_relation_exists(self):
        ks = KnowledgeSystem()
        ks.add_entity("zyrquen", {"type": "AI"})
        ks.add_entity("phase_9", {"name": "Native Intelligence"})
        ks.add_relation("zyrquen", "phase_9")
        r = ReasoningEngine(ks).deduce(context="zyrquen", question="next phase?")
        self.assertEqual(r["status"], "lookup_only")
        self.assertTrue(r["related_knowledge_found"])
        self.assertIn("phase_9", r["reasoning_path"])
        self.assertIs(r["model_inference"], False)

    def test_no_knowledge_found_without_relation(self):
        ks = KnowledgeSystem()
        ks.add_entity("zyrquen", {"type": "AI"})
        r = ReasoningEngine(ks).deduce(context="zyrquen", question="next phase?")
        self.assertEqual(r["status"], "no_knowledge_found")
        self.assertFalse(r["related_knowledge_found"])
        self.assertIs(r["model_inference"], False)


if __name__ == "__main__":
    unittest.main()
