"""Tests for ZYRQUEN Native-Only sequential pipeline (train -> evaluate -> regression -> approve)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))

from v2.native_pipeline import (  # noqa: E402
    main as pipeline_main,
    stage_approve,
    stage_evaluate,
    stage_regression,
    stage_resume,
    stage_train,
)


class NativePipelineTests(unittest.TestCase):
    def test_sequential_pipeline_runs_and_enforces_fail_closed_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="zyrquen_pipe_") as tmp:
            art_dir = Path(tmp)

            manifest = stage_train(art_dir, backend="pure", seed=42, steps_p1=4, steps_p2=4)
            self.assertEqual(manifest["backend"], "pure")
            self.assertFalse(manifest["external_models_used"])
            self.assertEqual(manifest["leakage_count"], 0)
            ckpt_path = art_dir / manifest["candidate_checkpoint"]
            self.assertTrue(ckpt_path.is_file())
            self.assertTrue(ckpt_path.with_suffix(ckpt_path.suffix + ".sha256").is_file())

            eval_res = stage_evaluate(art_dir)
            self.assertEqual(eval_res["checkpoint_sha256"], manifest["candidate_sha256"])
            self.assertEqual(eval_res["leakage_count"], 0)
            self.assertIn("candidate_unseen", eval_res)

            reg_res = stage_regression(art_dir)
            self.assertEqual(reg_res["checkpoint_sha256"], manifest["candidate_sha256"])
            self.assertIn("candidate_regression", reg_res)

            # With only 4 pure-Python steps from random init, unseen_pass_rate is 0 -> fail-closed REJECTED_BY_GATE
            rc = pipeline_main(["approve", "--artifact-dir", str(art_dir)])
            self.assertEqual(rc, 3)

            approval_path = ckpt_path.with_suffix(ckpt_path.suffix + ".approval.json")
            self.assertTrue(approval_path.is_file())
            approval_data = json.loads(approval_path.read_text(encoding="utf-8"))
            self.assertFalse(approval_data["approved"])
            self.assertEqual(approval_data["status"], "REJECTED_BY_GATE")

            # Checkpoint continuity: load candidate checkpoint and train 2 more steps without overwriting
            cont = stage_resume(art_dir, steps=2)
            self.assertTrue(cont["weights_preserved_continuity"])
            self.assertEqual(cont["global_step_before"], 8)
            self.assertEqual(cont["global_step_after"], 10)
            resumed_ckpt = art_dir / cont["resumed_checkpoint"]
            self.assertTrue(resumed_ckpt.is_file())
            self.assertNotEqual(resumed_ckpt, ckpt_path)
            self.assertNotEqual(cont["resumed_sha256"], manifest["candidate_sha256"])

    def test_tampered_checkpoint_blocks_evaluation_regression_and_approval(self) -> None:
        with tempfile.TemporaryDirectory(prefix="zyrquen_tamper_") as tmp:
            art_dir = Path(tmp)
            manifest = stage_train(art_dir, backend="pure", seed=7, steps_p1=2, steps_p2=2)
            stage_evaluate(art_dir)
            stage_regression(art_dir)

            ckpt_path = art_dir / manifest["candidate_checkpoint"]
            ckpt_path.write_bytes(ckpt_path.read_bytes() + b"\x00")

            with self.assertRaises(ValueError):
                stage_evaluate(art_dir)
            with self.assertRaises(ValueError):
                stage_regression(art_dir)
            with self.assertRaises(ValueError):
                stage_approve(art_dir)


if __name__ == "__main__":
    unittest.main()
