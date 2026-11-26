"""Unit and contract tests for ZYRQUEN V2 Execution & Debugging Skills runner."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))

from v2.run_v2_exec_debug_skills import (  # noqa: E402
    build_exec_debug_splits,
    classify_error,
    run_exec_debug_experiment,
    verify_exec_debug_leakage,
)
from v2.zyrquen_v2_trainer import run_code_in_sandbox  # noqa: E402


class TestV2ExecDebugSkills(unittest.TestCase):
    def test_splits_are_disjoint_leak_free_and_references_pass_sandbox(self) -> None:
        train_ex, val_ex, heldout_ex = build_exec_debug_splits()
        self.assertEqual(len(train_ex), 18)
        self.assertEqual(len(val_ex), 2)
        self.assertEqual(len(heldout_ex), 3)

        self.assertEqual(verify_exec_debug_leakage(train_ex, val_ex, heldout_ex), [])

        for ex in train_ex + val_ex + heldout_ex:
            ok, msg = run_code_in_sandbox(ex.full_text, ex.test_code)
            self.assertTrue(ok, f"Reference failed for {ex.task_id}: {msg}")

    def test_error_classification_categories(self) -> None:
        self.assertEqual(classify_error(True, ""), "passed")
        self.assertEqual(classify_error(False, "timeout"), "timeout")
        self.assertEqual(classify_error(False, "IndentationError: unexpected indent"), "SyntaxError")
        self.assertEqual(classify_error(False, "NameError: name 'x' is not defined"), "NameError")
        self.assertEqual(classify_error(False, "AssertionError"), "AssertionError")

    def test_pytorch_backend_fails_closed_when_torch_absent(self) -> None:
        has_torch = True
        try:
            import torch  # noqa: F401
        except ModuleNotFoundError:
            has_torch = False

        if not has_torch:
            with self.assertRaises(RuntimeError) as ctx:
                run_exec_debug_experiment(seeds=(42,), backend="pytorch")
            self.assertIn("BLOCKED", str(ctx.exception))

    def test_pure_backend_runs_end_to_end_with_audit_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            res = run_exec_debug_experiment(
                seeds=(42,),
                pure_steps_exec=2,
                pure_steps_debug=2,
                pure_ckpt_every=2,
                pure_max_new_tokens=16,
                out_dir=tmpdir,
                backend="pure",
            )
            self.assertEqual(res["backend"], "pure_python_3.11_stdlib")
            self.assertFalse(res["external_models_used"])
            self.assertEqual(res["leakage_count"], 0)
            self.assertTrue(Path(res["manifest_path"]).is_file())
            run42 = res["runs"][0]
            self.assertEqual(run42["global_step_final"], 4)
            p2_ckpt = Path(run42["checkpoints"]["stage2_exec_debug"]["path"])
            self.assertTrue(p2_ckpt.is_file())
            approval_path = Path(run42["checkpoints"]["stage2_exec_debug"]["approval_record"])
            self.assertTrue(approval_path.is_file())
            approval_data = json.loads(approval_path.read_text(encoding="utf-8"))
            if not approval_data["approved"]:
                self.assertEqual(approval_data["status"], "REJECTED_BY_GATE")
                self.assertIsNone(approval_data["approved_checkpoint"])
            self.assertIn("raw_output", run42["post_exec_and_debug"]["heldout"]["details"][0])


if __name__ == "__main__":
    unittest.main()
