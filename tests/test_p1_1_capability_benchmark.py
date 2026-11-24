"""Unit tests for ZYRQUEN Ω∞ P1-1 Capability Benchmark Test Suite."""

from __future__ import annotations

import json
import unittest

from tests.benchmark import (
    BENCHMARK_SCHEMA,
    FIXTURES_PATH,
    format_p1_1_markdown_report,
    load_benchmark_fixtures,
    run_p1_1_benchmark,
)


class TestP11CapabilityBenchmarkSuite(unittest.TestCase):
    def test_fixtures_are_valid_and_isolated_from_training_splits(self) -> None:
        self.assertTrue(FIXTURES_PATH.is_file())
        fx = load_benchmark_fixtures()
        self.assertEqual(fx["schema"], "zyrquen.p1_1.benchmark_fixtures.v1")
        self.assertEqual(fx["fixture_split"], "p1_1_held_out_eval")

        # Non-leakage test sections must never contain training/eval synthetic entity prefixes
        protected_sections = {
            k: v
            for k, v in fx.items()
            if k not in ("leakage_detection_cases", "forbidden_training_prefixes", "isolation_policy")
        }
        blob = json.dumps(protected_sections, ensure_ascii=False)
        for prefix in fx["forbidden_training_prefixes"]:
            self.assertNotIn(prefix, blob)

    def test_benchmark_report_is_reproducible_and_schema_complete(self) -> None:
        report_a = run_p1_1_benchmark()
        report_b = run_p1_1_benchmark()

        self.assertEqual(report_a["schema"], BENCHMARK_SCHEMA)
        self.assertEqual(report_a["baseline_digest_sha256"], report_b["baseline_digest_sha256"])
        self.assertEqual(report_a["summary"], report_b["summary"])
        self.assertEqual(report_a["category_scores"], report_b["category_scores"])
        self.assertEqual(report_a["tokenizer_metrics"], report_b["tokenizer_metrics"])

        expected_categories = {
            "positive",
            "negative_abstention",
            "math_logic",
            "graph_multi_hop",
            "memory_retrieval",
            "tokenizer_scoring",
            "leakage_detection",
            "native_model_inference",
        }
        self.assertEqual(set(report_a["category_scores"].keys()), expected_categories)
        for cat in expected_categories:
            self.assertGreater(report_a["category_scores"][cat]["total"], 0)

    def test_anti_fabrication_and_honest_blocked_reporting(self) -> None:
        report = run_p1_1_benchmark()
        self.assertTrue(report["leakage_detection"]["fixture_isolated"])
        self.assertTrue(report["leakage_detection"]["v10_injected_leak_caught"])
        self.assertTrue(report["leakage_detection"]["legacy_mock_isolated_from_scores"])
        self.assertFalse(report["leakage_detection"]["legacy_mock_detected"])
        self.assertTrue(report["leakage_detection"]["legacy_mock_removed"])
        self.assertEqual(report["leakage_detection"]["mock_in_real_evaluation"], 0)
        self.assertEqual(report["leakage_detection"]["slot_safe_entity_leaks"], [])
        self.assertIn("TE_E99421", report["leakage_detection"]["raw_corpus_bpe_leaks_detected"])

        # When torch is absent, native model inference must honestly report BLOCKED (never mock PASS)
        if not report["environment"]["torch_installed"]:
            native_cases = [c for c in report["cases"] if c["case_id"] == "native_model_sft_inference_probe"]
            self.assertEqual(len(native_cases), 1)
            self.assertEqual(native_cases[0]["status"], "BLOCKED")
            self.assertEqual(native_cases[0]["verification_status"], "BLOCKED")

    def test_known_core_baseline_gaps_are_accurately_captured(self) -> None:
        report = run_p1_1_benchmark()
        failure_types = {item["failure_type"] for item in report["failures_and_gaps"]}
        # These verify real current architectural gaps without fabricating passes or mutating core
        self.assertIn("SINGLE_HOP_LOOKUP_ONLY", failure_types)
        self.assertIn("NO_TRANSITIVE_LOGIC_INFERENCE", failure_types)
        self.assertIn("ENTITY_REGEX_OVERFIT_TO_SYNTHETIC_PREFIXES", failure_types)
        self.assertIn("EXACT_KEY_LOOKUP_ONLY_NO_SEMANTIC_RETRIEVAL", failure_types)
        self.assertIn("CONTEXT_MANAGER_NOT_WIRED_TO_INFERENCE_ROUTER", failure_types)
        self.assertIn("NO_PROVENANCE_OR_FRESHNESS_VALIDATION", failure_types)
        self.assertNotIn("LEGACY_MOCK_PRESENT", failure_types)

        cm = report["summary"]["confusion_matrix"]
        self.assertGreater(cm["TP"], 0)
        self.assertGreater(cm["TN"], 0)
        self.assertGreater(cm["FP"], 0)
        self.assertGreater(cm["FN"], 0)

    def test_markdown_formatter_renders_all_required_sections(self) -> None:
        report = run_p1_1_benchmark()
        md = format_p1_1_markdown_report(report)
        self.assertIn("P1-1 Baseline Benchmark Report", md)
        self.assertIn(report["baseline_digest_sha256"], md)
        self.assertIn("Confusion Matrix", md)
        self.assertIn("Failures & Blocked Gaps", md)


if __name__ == "__main__":
    unittest.main()
