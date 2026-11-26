"""Unit and contract tests for ZYRQUEN V2 Tool-Planning and 10-General-Skills runners."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))

from v2.run_v2_general_skills_suite import (  # noqa: E402
    build_general_skills_corpus,
    classify_error as classify_general_error,
    run_general_skills_suite,
    verify_general_skills_leakage,
)
from v2.run_v2_tool_planning_skills import (  # noqa: E402
    build_tool_planning_splits,
    classify_error as classify_tool_error,
    run_tool_planning_skill_training,
    verify_tool_planning_leakage,
)
from v2.zyrquen_v2_trainer import run_code_in_sandbox  # noqa: E402


class TestV2ToolPlanningAndGeneralSkills(unittest.TestCase):
    def test_tool_planning_splits_disjoint_leak_free_and_references_pass(self) -> None:
        train_ex, val_ex, heldout_ex = build_tool_planning_splits()
        self.assertEqual(len(train_ex), 12)
        self.assertEqual(len(val_ex), 2)
        self.assertEqual(len(heldout_ex), 3)
        self.assertEqual(verify_tool_planning_leakage(train_ex, val_ex, heldout_ex), [])

        for ex in train_ex + val_ex + heldout_ex:
            ok, msg = run_code_in_sandbox(ex.full_text, ex.test_code)
            self.assertTrue(ok, f"Reference failed for {ex.task_id}: {msg}")

    def test_general_skills_corpus_disjoint_leak_free_and_references_pass(self) -> None:
        train_ex, val_ex, heldout_ex = build_general_skills_corpus()
        self.assertEqual(len(train_ex), 16)
        self.assertEqual(len(val_ex), 2)
        self.assertEqual(len(heldout_ex), 3)
        all_skills = {s for ex in (train_ex + val_ex + heldout_ex) for s in ex.skills}
        self.assertEqual(len(all_skills), 10)
        self.assertEqual(verify_general_skills_leakage(train_ex, val_ex, heldout_ex), [])

        for ex in train_ex + val_ex + heldout_ex:
            ok, msg = run_code_in_sandbox(ex.full_text, ex.test_code)
            self.assertTrue(ok, f"Reference failed for {ex.task_id}: {msg}")

    def test_error_classification_and_pytorch_fail_closed(self) -> None:
        self.assertEqual(classify_tool_error(True, ""), "passed")
        self.assertEqual(classify_tool_error(False, "timeout"), "timeout")
        self.assertEqual(classify_general_error(False, "NameError: name 'x'"), "NameError")
        self.assertEqual(classify_general_error(False, "SyntaxError: bad"), "SyntaxError")

        has_torch = True
        try:
            import torch  # noqa: F401
        except ModuleNotFoundError:
            has_torch = False

        if not has_torch:
            with self.assertRaises(RuntimeError) as ctx1:
                run_tool_planning_skill_training(seeds=(42,), backend="pytorch")
            self.assertIn("BLOCKED", str(ctx1.exception))

            with self.assertRaises(RuntimeError) as ctx2:
                run_general_skills_suite(seeds=(42,), backend="pytorch")
            self.assertIn("BLOCKED", str(ctx2.exception))

    def test_tool_planning_and_general_skills_pure_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tp = run_tool_planning_skill_training(
                seeds=(42,),
                pure_steps_tool=2,
                pure_steps_plan=2,
                pure_ckpt_every=2,
                pure_max_new_tokens=16,
                out_dir=f"{tmpdir}/tp",
                backend="pure",
            )
            self.assertEqual(tp["backend"], "pure_python_3.11_stdlib")
            self.assertFalse(tp["external_models_used"])
            self.assertEqual(tp["leakage_count"], 0)
            self.assertTrue(Path(tp["manifest_path"]).is_file())
            tp_rec = Path(tp["runs"][0]["final_checkpoint"]["approval_record"])
            self.assertTrue(tp_rec.is_file())
            tp_app = json.loads(tp_rec.read_text(encoding="utf-8"))
            if not tp_app["approved"]:
                self.assertEqual(tp_app["status"], "REJECTED_BY_GATE")
                self.assertIsNone(tp_app["approved_checkpoint"])

            gs = run_general_skills_suite(
                seeds=(42,),
                pure_stage_steps=(2, 2, 2),
                pure_ckpt_every=2,
                pure_max_new_tokens=16,
                out_dir=f"{tmpdir}/gs",
                backend="pure",
            )
            self.assertEqual(gs["backend"], "pure_python_3.11_stdlib")
            self.assertEqual(len(gs["covered_skills"]), 10)
            self.assertFalse(gs["external_models_used"])
            self.assertEqual(gs["leakage_count"], 0)
            self.assertTrue(Path(gs["manifest_path"]).is_file())
            self.assertEqual(len(gs["runs"][0]["stage_history"]), 3)
            gs_rec = Path(gs["runs"][0]["final_checkpoint"]["approval_record"])
            self.assertTrue(gs_rec.is_file())
            gs_app = json.loads(gs_rec.read_text(encoding="utf-8"))
            if not gs_app["approved"]:
                self.assertEqual(gs_app["status"], "REJECTED_BY_GATE")
                self.assertIsNone(gs_app["approved_checkpoint"])
            self.assertIn("raw_output", gs["runs"][0]["post_all_stages"]["heldout_details"][0])


if __name__ == "__main__":
    unittest.main()
