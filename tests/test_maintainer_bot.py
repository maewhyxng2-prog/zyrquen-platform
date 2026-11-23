"""Comprehensive pure-stdlib unit & integration tests for ZYRQUEN Autonomous Repository Maintainer."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from apps.core.maintainer import (
    MaintainerPolicyError,
    PROTECTED_GATE_PATHS,
    RepositoryAuditor,
    ZyrquenMaintainerBot,
    authorize_action,
    is_protected_path,
    validate_patch_proposal,
)
from apps.core.workflow import ApprovalViolationError, CentralWorkflowOrchestrator
from apps.core.workflow.governance import TIER2_GATED_ACTIONS


class TestMaintainerPolicyAndPermissionMatrix(unittest.TestCase):
    def test_tier1_vs_tier2_permission_matrix(self) -> None:
        # Tier-1 auto-allowed actions
        for action in ("repo.read", "repo.audit", "tests.run", "branch.create", "pr.propose"):
            res = authorize_action(action)
            self.assertTrue(res["allowed"])
            self.assertEqual(res["tier"], "tier1_auto")

        # Tier-2 actions blocked unless explicit approval is provided
        for action in (
            "git.merge_main",
            "git.push",
            "training.execute",
            "deploy.production",
            "compute.paid_gpu",
            "architecture.modify",
            "data.delete",
        ):
            with self.assertRaises(MaintainerPolicyError):
                authorize_action(action, has_tier2_approval=False)

            approved = authorize_action(action, has_tier2_approval=True)
            self.assertTrue(approved["allowed"])
            self.assertEqual(approved["tier"], "tier2_approval")

        # Central governance must include git.merge_main
        self.assertIn("git.merge_main", TIER2_GATED_ACTIONS)

    def test_protected_gate_v10_and_anti_tamper_enforcement(self) -> None:
        # Protected V10, gate, and CI paths must always be blocked from automated edits
        for protected in (
            "apps/core/native/closure_audit.py",
            "apps/core/workflow/governance.py",
            "tools/close_v10d.py",
            "tools/audit_leakage_v10.py",
            ".github/workflows/security.yml",
            "docs/v10/V10_CLOSURE_STATUS.md",
            "apps/core/native/model_v8.py",
        ):
            self.assertTrue(is_protected_path(protected), f"Expected protected: {protected}")
            with self.assertRaises(MaintainerPolicyError):
                validate_patch_proposal(protected, "x = 1", "x = 2")

        # Path traversal & absolute paths must be blocked
        for bad_path in ("../outside.py", "/etc/passwd", ""):
            with self.assertRaises(MaintainerPolicyError):
                is_protected_path(bad_path)

        # Gate-tampering patterns blocked even on non-protected paths
        with self.assertRaises(MaintainerPolicyError):
            validate_patch_proposal(
                "apps/utils/helper.py",
                "verdict = 'FAIL'",
                "if verdict == 'FAIL': verdict = 'PASS'",
            )

        with self.assertRaises(MaintainerPolicyError):
            validate_patch_proposal(
                "apps/core/native/new_module.py",
                "def run():\n    return 1\n",
                "import openai\ndef run():\n    return 1\n",
            )

        # Reducing test assertions is forbidden
        with self.assertRaises(MaintainerPolicyError):
            validate_patch_proposal(
                "tests/test_sample.py",
                "def test_ok(self):\n    self.assertTrue(True)\n    self.assertEqual(1, 1)\n",
                "def test_ok(self):\n    self.assertTrue(True)\n",
            )


class TestRepositoryAuditorAndBotRemediation(unittest.TestCase):
    def _build_minimal_repo(self, root: Path) -> None:
        for rel in (
            "apps/api/main.py",
            "apps/core/workflow/orchestrator.py",
            "apps/core/workflow/governance.py",
            "apps/core/native/closure_audit.py",
            "apps/core/native/train.py",
            "apps/core/native/dataset_v11.py",
            ".github/workflows/security.yml",
            ".github/workflows/api-tests.yml",
            ".github/workflows/capability-development.yml",
            ".github/workflows/data-quality.yml",
        ):
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# clean placeholder\n", encoding="utf-8")

        (root / ".env.example").write_text("ZYRQUEN_ENV=development\n", encoding="utf-8")
        (root / "apps/api/requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
        (root / "apps/web").mkdir(parents=True, exist_ok=True)
        (root / "apps/web/package.json").write_text(
            json.dumps({"name": "web", "dependencies": {"next": "16.0.0"}}),
            encoding="utf-8",
        )
        for wf in (root / ".github/workflows").glob("*.yml"):
            wf.write_text("name: CI\non: [push]\npermissions:\n  contents: read\njobs: {}\n", encoding="utf-8")

    def test_audit_detects_syntax_security_native_policy_and_proposes_safe_pr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._build_minimal_repo(root)

            # Non-protected file with unsafe torch.load(...)
            loader_helper = root / "apps/core/loader_helper.py"
            loader_helper.write_text(
                "import torch\n\ndef load_ckpt(path):\n    return torch.load(path)\n",
                encoding="utf-8",
            )

            # Protected file also containing an issue -> MUST NEVER be auto-patched
            protected_file = root / "apps/core/native/closure_audit.py"
            protected_file.write_text(
                "import torch\n\ndef audit(path):\n    return torch.load(path)\n",
                encoding="utf-8",
            )

            # Broken syntax file in custom module
            bad_py = root / "apps/core/broken_mod.py"
            bad_py.write_text("def broken(:\n    pass\n", encoding="utf-8")

            bot = ZyrquenMaintainerBot(root)
            report = bot.run_audit(run_tests=False)
            self.assertEqual(report.overall_verdict, "FAIL")
            root_causes = {f.root_cause for f in report.findings}
            self.assertIn("python_syntax_error", root_causes)
            self.assertIn("unsafe_torch_load", root_causes)
            self.assertEqual(report.checks["native_only_compliance"], "PASS")
            self.assertEqual(report.checks["dependabot_config"], "not_on_current_branch")

            plan = bot.propose_remediation(report, branch_name="bot/fix-loader", verify_in_sandbox=True)
            self.assertEqual(plan.branch_name, "bot/fix-loader")
            self.assertEqual(plan.target_base_branch, "main")
            self.assertTrue(plan.tier2_required_before_merge)

            # Only non-protected loader_helper.py should be proposed for auto-patch
            proposed_paths = [p.file_path for p in plan.proposals]
            self.assertEqual(proposed_paths, ["apps/core/loader_helper.py"])
            self.assertEqual(plan.proposals[0].verification_status, "PASS")
            self.assertIn("weights_only=True", plan.proposals[0].unified_diff)

            # Protected closure_audit.py and non-auto-fixable syntax error remain in unresolved human-review list
            unresolved_paths = {u["file_path"]: u["disposition"] for u in plan.unresolved_findings}
            self.assertEqual(unresolved_paths["apps/core/native/closure_audit.py"], "BLOCKED_PROTECTED_PATH")
            self.assertEqual(unresolved_paths["apps/core/broken_mod.py"], "REQUIRES_HUMAN_OR_DESIGN_REVIEW")

            # Live workspace file itself must remain untouched (bot never mutates silently)
            self.assertNotIn("weights_only=True", loader_helper.read_text(encoding="utf-8"))

            # Merge to main strictly blocked without Tier-2 approval
            with self.assertRaises(MaintainerPolicyError):
                bot.merge_to_main(has_tier2_approval=False)

    def test_audit_catches_external_llm_in_native_core(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._build_minimal_repo(root)
            rogue = root / "apps/core/native/rogue_wrapper.py"
            rogue.write_text("import openai\n\ndef reason(x):\n    return openai\n", encoding="utf-8")

            report = RepositoryAuditor(root).run_audit(run_tests=False)
            self.assertEqual(report.checks["native_only_compliance"], "FAIL")
            self.assertEqual(report.overall_verdict, "FAIL")
            self.assertTrue(any(f.root_cause == "native_only_policy_violation" for f in report.findings))

    def test_real_workspace_audit_passes_native_only_and_syntax(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        report = RepositoryAuditor(repo_root).run_audit(run_tests=False)
        self.assertEqual(report.checks["native_only_compliance"], "PASS")
        self.assertEqual(report.checks["python_syntax_errors"], 0)
        self.assertGreater(report.files_scanned, 20)
        for p in PROTECTED_GATE_PATHS:
            self.assertTrue(is_protected_path(p))


class TestCentralWorkflowMaintainerIntegration(unittest.TestCase):
    def test_autonomous_maintainer_workflow_tier1_auto_then_tier2_merge_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mini_repo = tmp_path / "mini_repo"
            mini_repo.mkdir()
            TestRepositoryAuditorAndBotRemediation()._build_minimal_repo(mini_repo)
            (mini_repo / "apps/core/helper.py").write_text(
                "import torch\n\ndef load_it(p):\n    return torch.load(p)\n",
                encoding="utf-8",
            )

            orch = CentralWorkflowOrchestrator(
                db_path=tmp_path / "wf.db",
                work_dir=tmp_path,
                approval_secret="unit-test-secret-key-at-least-32-bytes",
            )
            try:
                # Trigger through single CentralWorkflowOrchestrator
                run = orch.trigger_workflow(
                    "project_dev.autonomous_maintainer",
                    payload={"repo_root": str(mini_repo), "branch_name": "bot/maintainer-test"},
                    requested_by_user_id="dev-1",
                )
                # Tier-1 steps finish, Tier-2 merge_to_main MUST pause at WAITING_APPROVAL
                self.assertEqual(run["status"], "WAITING_APPROVAL")
                steps = {s["step_key"]: s for s in run["steps"]}
                self.assertEqual(steps["audit_repo"]["status"], "COMPLETED")
                self.assertEqual(steps["propose_remediation"]["status"], "COMPLETED")
                self.assertEqual(steps["propose_remediation"]["output"]["proposal_count"], 1)
                self.assertEqual(steps["merge_to_main"]["status"], "WAITING_APPROVAL")

                approval_id = run["approvals"][0]["id"]
                self.assertEqual(run["approvals"][0]["action_type"], "git.merge_main")

                # Non-admin approval must fail
                with self.assertRaises(ApprovalViolationError):
                    orch.decide_approval_and_resume(
                        approval_id,
                        approve=True,
                        approver_user_id="dev-1",
                        approver_role="user",
                    )

                # Admin approval unlocks merge_to_main with HMAC verification
                resumed = orch.decide_approval_and_resume(
                    approval_id,
                    approve=True,
                    approver_user_id="admin-1",
                    approver_role="admin",
                    reason="Verified PR diff & sandbox check",
                )
                self.assertEqual(resumed["status"], "COMPLETED")
                resumed_steps = {s["step_key"]: s for s in resumed["steps"]}
                self.assertEqual(resumed_steps["merge_to_main"]["status"], "COMPLETED")
                self.assertEqual(resumed_steps["merge_to_main"]["output"]["approval_id"], approval_id)
                self.assertEqual(resumed_steps["merge_to_main"]["output"]["branch_name"], "bot/maintainer-test")
            finally:
                orch.shutdown(wait=True)

    def test_cli_audit_on_real_workspace(self) -> None:
        from tools.maintainer_bot import main as cli_main

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "audit.json"
            rc = cli_main(["--mode", "audit", "--json", "--out", str(out_path)])
            self.assertIn(rc, (0, 1))
            data = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema"], "zyrquen.maintainer.audit.v1")
            self.assertEqual(data["checks"]["native_only_compliance"], "PASS")


if __name__ == "__main__":
    unittest.main()
