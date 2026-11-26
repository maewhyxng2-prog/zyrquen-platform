"""Systematic P0 Acceptance Tests: Reality Over Appearance.

Covers:
1. Recommendation Verification (zero filler, verified evidence required)
2. Tool Availability Verification (usable/unverified/unavailable/not_found)
3. Source Authenticity (rejects placeholder domains & missing provenance)
4. Broken Link Detection (malformed URLs & repository doc links)
5. Unsupported Capability Detection (blocks unfinished runtime claims)
6. False Success Prevention (rejects fake PASS, inference=False, and mock scores)
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from apps.core.intelligence import ExecutionPolicy, ToolRegistry
from tests.benchmark.p0_reality_gate import (
    OUTPUT_STATUSES,
    detect_unsupported_capabilities,
    evaluate_recommendation_candidates,
    run_p0_reality_acceptance,
    validate_url_integrity,
    verify_evidence_record,
    verify_false_success_prevention,
    verify_repo_doc_links,
    verify_tool_availability,
)


class TestP0RealityOverAppearanceAcceptance(unittest.TestCase):
    def test_recommendation_verification_rejects_unverified_stale_and_empty_sets(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        res = evaluate_recommendation_candidates([
            {
                "name": "Real Verified Option",
                "availability_status": "AVAILABLE",
                "evidence": {
                    "source_id": "registry:tool-1",
                    "source_url": "https://docs.python.org/3/",
                    "retrieved_at": now_iso,
                    "evidence_content": "Verified reference documentation.",
                    "verification_status": "VERIFIED",
                    "freshness": "CURRENT",
                },
            },
            {
                "name": "Unverified Option",
                "availability_status": "AVAILABLE",
                "evidence": {
                    "source_id": "registry:tool-2",
                    "source_url": "https://docs.python.org/3/",
                    "retrieved_at": now_iso,
                    "evidence_content": "Pending verification.",
                    "verification_status": "UNVERIFIED",
                },
            },
            {
                "name": "Missing Evidence Option",
                "availability_status": "AVAILABLE",
                "evidence": None,
            },
        ])
        self.assertEqual(res["overall_status"], "VERIFIED")
        self.assertEqual([x["name"] for x in res["recommended"]], ["Real Verified Option"])
        self.assertEqual(len(res["rejected"]), 2)
        self.assertEqual(res["filler_items_added"], 0)

        # When zero verified options remain, must abstain honestly as NOT_FOUND with no filler
        empty_res = evaluate_recommendation_candidates([res["rejected"][0]])  # type: ignore[list-item]
        self.assertEqual(empty_res["overall_status"], "NOT_FOUND")
        self.assertEqual(empty_res["recommended"], [])
        self.assertEqual(empty_res["filler_items_added"], 0)

    def test_tool_availability_verification_enforces_behavior_matrix(self) -> None:
        reg = ToolRegistry()
        reg.register({
            "name": "web_lookup",
            "description": "Read-only lookup",
            "effect": "read_only",
            "required_permission": "tool:search",
            "input_schema": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
                "additionalProperties": False,
            },
        })
        policy = ExecutionPolicy(allow_read_only=True, allow_side_effecting=False)

        verified = verify_tool_availability(
            "web_lookup",
            registry=reg,
            policy=policy,
            granted_permissions={"tool:search"},
            runtime_executor_wired=True,
            service_available=True,
        )
        self.assertEqual(verified["output_status"], "VERIFIED")
        self.assertTrue(verified["usable"])

        unverified = verify_tool_availability(
            "web_lookup",
            registry=reg,
            policy=policy,
            granted_permissions={"tool:search"},
            runtime_executor_wired=False,
            service_available=True,
        )
        self.assertEqual(unverified["output_status"], "UNVERIFIED")
        self.assertFalse(unverified["usable"])

        unavailable = verify_tool_availability(
            "web_lookup",
            registry=reg,
            policy=policy,
            granted_permissions={"tool:search"},
            runtime_executor_wired=True,
            service_available=False,
        )
        self.assertEqual(unavailable["output_status"], "UNAVAILABLE")
        self.assertFalse(unavailable["usable"])

        not_found = verify_tool_availability(
            "nonexistent_tool",
            registry=reg,
            policy=policy,
            granted_permissions={"tool:search"},
        )
        self.assertEqual(not_found["output_status"], "NOT_FOUND")
        self.assertFalse(not_found["usable"])

    def test_source_authenticity_and_stale_evidence_rejection(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        # Reject placeholder domains
        for bad_url in (
            "https://example.com/item",
            "https://placeholder.invalid/spec",
            "http://localhost:9999/api",
            "https://service.test/data",
        ):
            check = validate_url_integrity(bad_url)
            self.assertFalse(check["valid"], f"Expected rejection for placeholder URL: {bad_url}")

        # Reject missing source_id / evidence_content / stale timestamps
        missing_src = verify_evidence_record({
            "source_id": "",
            "retrieved_at": now_iso,
            "evidence_content": "Some fact",
            "verification_status": "VERIFIED",
        })
        self.assertEqual(missing_src["status"], "UNVERIFIED")
        self.assertFalse(missing_src["accepted"])

        stale = verify_evidence_record({
            "source_id": "official:spec",
            "source_url": "https://docs.python.org/3/",
            "retrieved_at": "2018-01-01T00:00:00Z",
            "evidence_content": "Old info",
            "verification_status": "VERIFIED",
        })
        self.assertEqual(stale["status"], "STALE")
        self.assertFalse(stale["accepted"])

    def test_broken_link_detection_and_repo_doc_links(self) -> None:
        for broken in (
            "",
            "   ",
            "not-a-valid-url://broken",
            "ftp://files.python.org/pub",
            "javascript:alert(1)",
            "https://missingtld/page",
            "https://bad host name.org/path",
        ):
            res = validate_url_integrity(broken)
            self.assertFalse(res["valid"], f"Expected broken URL rejection for: {broken!r}")

        self.assertTrue(validate_url_integrity("https://docs.python.org/3/library/unittest.html")["valid"])
        doc_links = verify_repo_doc_links()
        self.assertTrue(doc_links["passed"], f"Missing required P0 docs: {doc_links['missing_files']}")

    def test_unsupported_capability_and_false_success_prevention(self) -> None:
        unsupported = detect_unsupported_capabilities()
        self.assertTrue(unsupported["passed"], f"Unsupported capability failure: {unsupported}")

        false_success = verify_false_success_prevention()
        self.assertTrue(false_success["passed"], f"False success gate failure: {false_success}")
        self.assertTrue(false_success["checks"]["zero_mock_in_real_evaluation"])
        self.assertTrue(false_success["checks"]["ui_preview_no_fabricated_eval_scores"])

    def test_end_to_end_p0_reality_acceptance_gate_passes(self) -> None:
        report = run_p0_reality_acceptance()
        self.assertEqual(report["schema"], "zyrquen.p0.reality_acceptance.v1")
        self.assertEqual(report["overall_status"], "PASS")
        self.assertTrue(all(report["gates"].values()))
        self.assertIn(report["recommendation_audit"]["overall_status"], OUTPUT_STATUSES)


if __name__ == "__main__":
    unittest.main()
