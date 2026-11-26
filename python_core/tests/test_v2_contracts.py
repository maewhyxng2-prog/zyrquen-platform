"""Unit tests for ZYRQUEN V2 architecture, RoPE backprop, optimizer resume, and safety gates."""

import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))

from v2.run_zyrquen_v2_experiment import build_leak_free_datasets  # noqa: E402
from v2.zyrquen_v2_pure import (  # noqa: E402
    PureContinualTrainerV2,
    PureNativeTransformerLMV2,
    PureZyrquenV2Config,
    verify_v2_gradients,
)
from v2.zyrquen_v2_trainer import (  # noqa: E402
    ApprovalGate,
    ByteTokenizer,
    CodingTask,
    EvalReport,
    detect_task_leakage,
    run_code_in_sandbox,
)


class TestZyrquenV2Contracts(unittest.TestCase):
    def test_byte_tokenizer_roundtrip_and_special_ids(self) -> None:
        tok = ByteTokenizer()
        text = "def avg(x):\n    return sum(x) / len(x)  # ภาษาไทย\n"
        ids = tok.encode(text, add_eos=True)
        self.assertEqual(ids[-1], tok.eos_id)
        self.assertNotIn(tok.pad_id, ids)
        decoded = tok.decode(ids + [tok.pad_id, 65, 66], stop_at_eos=True)
        self.assertEqual(decoded, text)

    def test_rope_swiglu_analytical_gradients_match_finite_diff(self) -> None:
        res = verify_v2_gradients()
        self.assertTrue(res["passed"], f"Gradient check failed: {res}")

    def test_pure_v2_optimizer_resume_and_context_extension(self) -> None:
        tok = ByteTokenizer()
        cfg = PureZyrquenV2Config(
            vocab_size=tok.vocab_size,
            d_model=8,
            n_heads=2,
            n_layers=1,
            d_ff=16,
            base_seq_len=32,
            max_seq_len=64,
        )
        trainer = PureContinualTrainerV2(
            PureNativeTransformerLMV2(cfg), tok, lr=0.01, seed=7
        )
        trainer.train_steps(["def f(x):\n    return x + 1\n"], steps=4, batch_size=2, replay_ratio=0.0)
        trainer.snapshot_consolidation_state(["def f(x):\n    return x + 1\n"])
        self.assertEqual(trainer.global_step, 4)

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path, sha = trainer.save_checkpoint(Path(tmpdir) / "v2.json.gz")
            resumed = PureContinualTrainerV2.load_checkpoint(
                ckpt_path, tok, expected_sha256=sha, resume_optimizer=True
            )
            self.assertEqual(resumed.global_step, 4)
            self.assertEqual(len(resumed.replay_buffer), 1)
            self.assertTrue(bool(resumed.anchor_params))
            resumed.model.extend_context(128)
            self.assertEqual(resumed.model.cfg.max_seq_len, 128)
            logits, _ = resumed.model.forward([65] * 80, record_cache=False)
            self.assertEqual(len(logits), 80)

    def test_experiment_datasets_have_zero_leakage(self) -> None:
        p1, p2, _reg, unseen = build_leak_free_datasets()
        leaks = detect_task_leakage(p1 + p2, unseen)
        self.assertEqual(leaks, [])

    def test_leakage_detector_blocks_overlapping_function_or_reference(self) -> None:
        train = ["def running_mean(arr):\n    return sum(arr) / len(arr)\n"]
        leaked_task = CodingTask(
            task_id="bad",
            prompt="def running_mean(arr):\n    return ",
            reference_solution=train[0],
            test_code="assert running_mean([2, 4]) == 3",
        )
        leaks = detect_task_leakage(train, [leaked_task])
        self.assertGreaterEqual(len(leaks), 1)

    def test_sandbox_executes_valid_and_rejects_broken_code(self) -> None:
        ok, _ = run_code_in_sandbox(
            "def add_nums(a, b):\n    return a + b\n",
            "assert add_nums(2, 3) == 5",
        )
        self.assertTrue(ok)

        bad_ok, msg = run_code_in_sandbox(
            "def add_nums(a, b):\n    return a - b\n",
            "assert add_nums(2, 3) == 5",
        )
        self.assertFalse(bad_ok)
        self.assertIn("AssertionError", msg)

    def test_approval_gate_rejects_zero_unseen_and_regression_drop(self) -> None:
        gate = ApprovalGate(min_unseen_gain=0.01, max_regression_drop=0.05)

        zero_base = EvalReport(avg_loss=2.0, exec_pass_rate=0.0, passed_count=0, total_count=2)
        zero_cand = EvalReport(avg_loss=1.5, exec_pass_rate=0.0, passed_count=0, total_count=2)
        reg_ok = EvalReport(avg_loss=0.2, exec_pass_rate=1.0, passed_count=2, total_count=2)

        d1 = gate.evaluate(zero_base, zero_cand, reg_ok, reg_ok)
        self.assertFalse(d1.approved)

        better_cand = EvalReport(avg_loss=1.0, exec_pass_rate=0.5, passed_count=1, total_count=2)
        reg_drop = EvalReport(avg_loss=0.9, exec_pass_rate=0.5, passed_count=1, total_count=2)
        d2 = gate.evaluate(zero_base, better_cand, reg_ok, reg_drop)
        self.assertFalse(d2.approved)

        d3 = gate.evaluate(zero_base, better_cand, reg_ok, reg_ok, leakage_count=1)
        self.assertFalse(d3.approved)

        d4 = gate.evaluate(zero_base, better_cand, reg_ok, reg_ok, leakage_count=0)
        self.assertTrue(d4.approved)


from v2.zyrquen_v2_longctx_bench import build_longctx_benchmark  # noqa: E402
from v2.zyrquen_v2_suite import build_ablation_datasets  # noqa: E402


class TestZyrquenV2ExtendedContracts(unittest.TestCase):
    def test_ablation_suite_datasets_have_zero_leakage(self) -> None:
        p1, p2, ret, unseen = build_ablation_datasets()
        self.assertEqual(detect_task_leakage(p1 + p2, unseen), [])
        self.assertGreaterEqual(len(ret), 3)
        self.assertGreaterEqual(len(unseen), 3)

    def test_longctx_crossref_prompts_exceed_256_bytes_and_pass_references(self) -> None:
        p1, p2, ret, unseen = build_longctx_benchmark()
        self.assertEqual(detect_task_leakage(p1 + p2, unseen), [])
        for task in ret + unseen:
            self.assertGreater(len(task.prompt.encode("utf-8")), 256)
            ok, msg = run_code_in_sandbox(task.reference_solution, task.test_code)
            self.assertTrue(ok, f"Reference failed for {task.task_id}: {msg}")


if __name__ == "__main__":
    unittest.main()
