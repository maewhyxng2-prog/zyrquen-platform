"""Unit and contract tests for ZYRQUEN V2 Multi-Step Workflow, Compositional Generalization, and Autonomous Skills suites."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))

from v2.run_v2_autonomous_agent_skills import (  # noqa: E402
    AutonomousSkillTask,
    VerifiedExperienceBuffer,
    build_autonomous_skill_splits,
    run_autonomous_agent_skills,
    verify_autonomous_skills_leakage,
)
from v2.run_v2_compositional_generalization import (  # noqa: E402
    CompositionalSandboxEvaluator,
    build_compositional_generalization_splits,
    run_compositional_generalization_suite,
    verify_compositional_leakage,
)
from v2.run_v2_multi_step_agent_workflow import (  # noqa: E402
    WorkflowSandboxRunner,
    build_multi_step_workflow_splits,
    run_multi_step_workflow_suite,
    verify_workflow_leakage,
)
from v2.zyrquen_v2_trainer import CodingTask, run_code_in_sandbox  # noqa: E402


class TestV2NewSuites(unittest.TestCase):
    def test_all_three_corpora_disjoint_leak_free_and_references_pass(self) -> None:
        wf_tr, wf_val, wf_ho = build_multi_step_workflow_splits()
        self.assertEqual((len(wf_tr), len(wf_val), len(wf_ho)), (12, 2, 3))
        self.assertEqual(verify_workflow_leakage(wf_tr, wf_val, wf_ho), [])
        for ex in wf_tr + wf_val + wf_ho:
            ok, msg = run_code_in_sandbox(ex.full_text, ex.test_code)
            self.assertTrue(ok, f"Workflow ref failed {ex.task_id}: {msg}")

        cg_tr, cg_val, cg_ho = build_compositional_generalization_splits()
        self.assertEqual((len(cg_tr), len(cg_val), len(cg_ho)), (12, 2, 3))
        self.assertEqual(verify_compositional_leakage(cg_tr, cg_val, cg_ho), [])
        for ex in cg_tr + cg_val + cg_ho:
            ok, msg = run_code_in_sandbox(ex.full_text, ex.test_code)
            self.assertTrue(ok, f"Compositional ref failed {ex.task_id}: {msg}")

        aut_tr, aut_val, aut_ho = build_autonomous_skill_splits()
        self.assertEqual((len(aut_tr), len(aut_val), len(aut_ho)), (12, 2, 3))
        self.assertEqual(verify_autonomous_skills_leakage(aut_tr, aut_val, aut_ho), [])
        for ex in aut_tr + aut_val + aut_ho:
            ok, msg = run_code_in_sandbox(ex.full_text, ex.test_code)
            self.assertTrue(ok, f"Autonomous ref failed {ex.task_id}: {msg}")

    def test_workflow_runner_diagnose_and_recover(self) -> None:
        prompts: list[str] = []

        def fake_gen(prompt: str) -> str:
            prompts.append(prompt)
            if "Recovery attempt 2" in prompt:
                return "def mul2(x):\n    return x * 2\n"
            return "def mul2(x):\n    return x + 1\n"

        runner = WorkflowSandboxRunner(fake_gen, loss_fn=lambda _: 0.4, max_attempts=3)
        task = CodingTask(
            task_id="wf_t",
            prompt="def mul2(x):\n    return ",
            test_code="assert mul2(3) == 6 and mul2(4) == 8",
            reference_solution="def mul2(x):\n    return x * 2\n",
        )
        first_rep, final_rep = runner.evaluate([task])
        self.assertEqual(first_rep.passed_count, 0)
        self.assertEqual(final_rep.passed_count, 1)
        self.assertTrue(final_rep.details[0]["recovered_on_retry"])
        self.assertEqual(final_rep.details[0]["attempts_used"], 2)
        self.assertIn("Diagnose [AssertionError]", prompts[1])

    def test_compositional_evaluator_retry(self) -> None:
        def fake_gen(prompt: str) -> str:
            if "Composition retry 2" in prompt:
                return "def sq(x):\n    return x * x\n"
            return "def sq(x):\n    return undefined_var\n"

        ev = CompositionalSandboxEvaluator(fake_gen, loss_fn=lambda _: 0.3, max_attempts=2)
        task = CodingTask(
            task_id="cg_t",
            prompt="def sq(x):\n    return ",
            test_code="assert sq(5) == 25",
            reference_solution="def sq(x):\n    return x * x\n",
        )
        first_rep, final_rep = ev.evaluate([task])
        self.assertEqual(first_rep.error_breakdown["NameError"], 1)
        self.assertEqual(final_rep.passed_count, 1)

    def test_verified_experience_buffer_train_only_and_filter(self) -> None:
        buf = VerifiedExperienceBuffer()
        tr_tasks, _, ho_tasks = build_autonomous_skill_splits()
        with self.assertRaises(ValueError):
            buf.collect_verified(ho_tasks, lambda p: p)

        sample = [
            AutonomousSkillTask(
                "ok_train", "f", ("Programming",), "train", "plan_exec_verify",
                "def f(x):\n    return ", "x + 1\n", "assert f(2) == 3"
            ),
            AutonomousSkillTask(
                "bad_train", "f", ("Programming",), "train", "plan_exec_verify",
                "def g(x):\n    return ", "x + 1\n", "assert g(2) == 99"
            ),
        ]

        def gen(p: str) -> str:
            return p + "x + 1\n"

        stats = buf.collect_verified(sample, gen)
        self.assertEqual(stats["checked"], 2)
        self.assertEqual(stats["newly_verified"], 1)
        self.assertEqual(len(buf.texts()), 1)
        self.assertEqual(len(tr_tasks), 12)

    def test_pytorch_fail_closed_when_missing(self) -> None:
        has_torch = True
        try:
            import torch  # noqa: F401
        except ModuleNotFoundError:
            has_torch = False
        if not has_torch:
            for fn in (
                run_multi_step_workflow_suite,
                run_compositional_generalization_suite,
                run_autonomous_agent_skills,
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    fn(seeds=(42,), backend="pytorch")
                self.assertIn("BLOCKED", str(ctx.exception))

    def test_all_three_suites_pure_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            r1 = run_multi_step_workflow_suite(
                seeds=(42,),
                pure_phase_steps=(2, 2, 2),
                pure_ckpt_every=2,
                pure_max_new_tokens=16,
                max_attempts=3,
                out_dir=f"{tmpdir}/wf",
                backend="pure",
            )
            self.assertEqual(r1["backend"], "pure_python_3.11_stdlib")
            self.assertEqual(r1["leakage_count"], 0)
            self.assertFalse(r1["external_models_used"])
            self.assertTrue(Path(r1["manifest_path"]).is_file())
            self.assertTrue(Path(r1["runs"][0]["final_checkpoint"]["approval_record"]).is_file())

            r2 = run_compositional_generalization_suite(
                seeds=(42,),
                pure_stage_steps=(2, 2, 2),
                pure_ckpt_every=2,
                pure_max_new_tokens=16,
                max_attempts=2,
                out_dir=f"{tmpdir}/cg",
                backend="pure",
            )
            self.assertEqual(r2["backend"], "pure_python_3.11_stdlib")
            self.assertEqual(r2["leakage_count"], 0)
            self.assertFalse(r2["external_models_used"])
            self.assertTrue(Path(r2["manifest_path"]).is_file())

            r3 = run_autonomous_agent_skills(
                seeds=(42,),
                pure_phase_steps=(2, 2, 2),
                pure_ckpt_every=2,
                pure_max_new_tokens=16,
                max_attempts=2,
                out_dir=f"{tmpdir}/aut",
                backend="pure",
            )
            self.assertEqual(r3["backend"], "pure_python_3.11_stdlib")
            self.assertEqual(r3["leakage_count"], 0)
            self.assertFalse(r3["external_models_used"])
            self.assertTrue(Path(r3["manifest_path"]).is_file())
            app = json.loads(
                Path(r3["runs"][0]["final_checkpoint"]["approval_record"]).read_text(encoding="utf-8")
            )
            self.assertIn(app["status"], ("APPROVED", "REJECTED_BY_GATE"))


if __name__ == "__main__":
    unittest.main()
