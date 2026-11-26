"""Unit and contract tests for ZYRQUEN V2 Full 10-General-Skills Self-Correction suite."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))

from v2.run_v2_full_general_skills import (  # noqa: E402
    SelfCorrectingSandboxEvaluator,
    build_rich_10_skill_corpus,
    classify_error,
    run_full_general_skills_suite,
    verify_full_general_skills_leakage,
)
from v2.zyrquen_v2_trainer import CodingTask, run_code_in_sandbox  # noqa: E402


class TestV2FullGeneralSkills(unittest.TestCase):
    def test_rich_corpus_disjoint_leak_free_and_references_pass(self) -> None:
        train_ex, val_ex, heldout_ex = build_rich_10_skill_corpus()
        self.assertEqual(len(train_ex), 24)
        self.assertEqual(len(val_ex), 2)
        self.assertEqual(len(heldout_ex), 3)
        all_skills = {s for ex in (train_ex + val_ex + heldout_ex) for s in ex.skills}
        self.assertEqual(len(all_skills), 10)
        self.assertEqual(verify_full_general_skills_leakage(train_ex, val_ex, heldout_ex), [])

        for ex in train_ex + val_ex + heldout_ex:
            ok, msg = run_code_in_sandbox(ex.full_text, ex.test_code)
            self.assertTrue(ok, f"Reference failed for {ex.task_id}: {msg}")

    def test_self_correcting_evaluator_tracks_first_and_repaired_pass(self) -> None:
        calls: list[str] = []

        def fake_gen(prompt: str) -> str:
            calls.append(prompt)
            if "Self-Correction attempt 2" in prompt:
                return "def add_two(a, b):\n    return a + b\n"
            return "def add_two(a, b):\n    return a - b\n"

        evaluator = SelfCorrectingSandboxEvaluator(
            generate_fn=fake_gen,
            loss_fn=lambda _: 0.5,
            max_attempts=2,
        )
        task = CodingTask(
            task_id="t1",
            prompt="def add_two(a, b):\n    return ",
            test_code="assert add_two(2, 3) == 5",
            reference_solution="def add_two(a, b):\n    return a + b\n",
        )
        first_rep, final_rep = evaluator.evaluate([task])
        self.assertEqual(first_rep.passed_count, 0)
        self.assertEqual(final_rep.passed_count, 1)
        self.assertEqual(final_rep.details[0]["attempts_used"], 2)
        self.assertFalse(final_rep.details[0]["first_attempt_passed"])
        self.assertTrue(final_rep.details[0]["passed"])
        self.assertEqual(len(calls), 2)

    def test_error_classification_and_pytorch_fail_closed(self) -> None:
        self.assertEqual(classify_error(True, ""), "passed")
        self.assertEqual(classify_error(False, "timeout"), "timeout")
        self.assertEqual(classify_error(False, "AssertionError"), "AssertionError")

        has_torch = True
        try:
            import torch  # noqa: F401
        except ModuleNotFoundError:
            has_torch = False

        if not has_torch:
            with self.assertRaises(RuntimeError) as ctx:
                run_full_general_skills_suite(seeds=(42,), backend="pytorch")
            self.assertIn("BLOCKED", str(ctx.exception))

    def test_full_general_skills_pure_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            res = run_full_general_skills_suite(
                seeds=(42,),
                pure_stage_steps=(2, 2, 2),
                pure_ckpt_every=2,
                pure_max_new_tokens=16,
                max_attempts=2,
                out_dir=f"{tmpdir}/full_gs",
                backend="pure",
            )
            self.assertEqual(res["backend"], "pure_python_3.11_stdlib")
            self.assertEqual(len(res["covered_skills"]), 10)
            self.assertFalse(res["external_models_used"])
            self.assertEqual(res["leakage_count"], 0)
            self.assertTrue(Path(res["manifest_path"]).is_file())
            self.assertEqual(len(res["runs"][0]["stage_history"]), 3)
            rec = Path(res["runs"][0]["final_checkpoint"]["approval_record"])
            self.assertTrue(rec.is_file())
            app = json.loads(rec.read_text(encoding="utf-8"))
            if not app["approved"]:
                self.assertEqual(app["status"], "REJECTED_BY_GATE")
                self.assertIsNone(app["approved_checkpoint"])
            details = res["runs"][0]["post_all_stages"]["heldout_details"]
            self.assertIn("attempts_used", details[0])
            self.assertIn("first_attempt_passed", details[0])
            self.assertIn("raw_output", details[0])


if __name__ == "__main__":
    unittest.main()
