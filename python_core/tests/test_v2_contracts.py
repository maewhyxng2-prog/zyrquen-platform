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


from v2.run_v2_expanded_experiment import (  # noqa: E402
    _classify_failure,
    _failure_breakdown,
    run_diverse_experiment,
)
from v2.zyrquen_v2_longctx_bench import build_longctx_benchmark  # noqa: E402
from v2.zyrquen_v2_suite import (  # noqa: E402
    aggregate_multi_seed_runs,
    build_ablation_datasets,
    build_diverse_training_corpus,
    run_suite,
)
from v2.zyrquen_v2_trainer import (  # noqa: E402
    GateDecision,
    SandboxEvaluator,
    record_checkpoint_approval,
)


class TestZyrquenV2ExtendedContracts(unittest.TestCase):
    def test_ablation_suite_datasets_have_zero_leakage_and_preserve_three_unseen(self) -> None:
        p1_div, p2_div = build_diverse_training_corpus()
        self.assertGreaterEqual(len(p1_div), 12)
        self.assertGreaterEqual(len(p2_div), 12)

        p1, p2, ret, unseen = build_ablation_datasets()
        self.assertEqual(p1, p1_div)
        self.assertEqual(p2, p2_div)
        self.assertEqual(detect_task_leakage(p1 + p2, unseen), [])
        self.assertGreaterEqual(len(ret), 3)
        self.assertEqual(
            [(t.task_id, t.prompt, t.reference_solution, t.test_code) for t in unseen],
            [
                (
                    "unseen_avg",
                    "def avg_or_zero(vals):\n    return ",
                    "def avg_or_zero(vals):\n    return sum(vals) / len(vals) if vals else 0.0\n",
                    "assert abs(avg_or_zero([2.0, 4.0, 6.0]) - 4.0) < 1e-6 and avg_or_zero([]) == 0.0",
                ),
                (
                    "unseen_dedup_sort",
                    "def distinct_ordered(seq):\n    return ",
                    "def distinct_ordered(seq):\n    return sorted(set(seq))\n",
                    "assert distinct_ordered([4, 2, 4, 1]) == [1, 2, 4]",
                ),
                (
                    "unseen_span",
                    "def diff_range(nums):\n    return ",
                    "def diff_range(nums):\n    return max(nums) - min(nums) if nums else 0\n",
                    "assert diff_range([3, 11, 2, 8]) == 9 and diff_range([]) == 0",
                ),
            ],
        )

    def test_longctx_crossref_prompts_exceed_256_bytes_and_pass_references(self) -> None:
        p1, p2, ret, unseen = build_longctx_benchmark()
        self.assertEqual(detect_task_leakage(p1 + p2, unseen), [])
        for task in ret + unseen:
            self.assertGreater(len(task.prompt.encode("utf-8")), 256)
            ok, msg = run_code_in_sandbox(task.reference_solution, task.test_code)
            self.assertTrue(ok, f"Reference failed for {task.task_id}: {msg}")

    def test_sandbox_evaluator_records_raw_output_and_error_breakdown(self) -> None:
        tasks = [
            CodingTask(
                task_id="t_pass",
                prompt="def f1(x):\n    return ",
                test_code="assert f1(2) == 3",
            ),
            CodingTask(
                task_id="t_syntax",
                prompt="def f2(x):\n    return ",
                test_code="assert f2(2) == 3",
            ),
            CodingTask(
                task_id="t_assert",
                prompt="def f3(x):\n    return ",
                test_code="assert f3(2) == 3",
            ),
            CodingTask(
                task_id="t_name",
                prompt="def f4(x):\n    return ",
                test_code="assert f4(2) == 3",
            ),
        ]
        outputs = {
            tasks[0].prompt: "def f1(x):\n    return x + 1\n",
            tasks[1].prompt: "def f2(x):\n    return ((\n",
            tasks[2].prompt: "def f3(x):\n    return x\n",
            tasks[3].prompt: "def f4(x):\n    return missing_var\n",
        }
        evaluator = SandboxEvaluator(
            generate_fn=lambda p: outputs[p],
            loss_fn=lambda _texts: 0.5,
        )
        rep = evaluator.evaluate(tasks)
        self.assertEqual(rep.passed_count, 1)
        self.assertEqual(rep.error_breakdown["passed"], 1)
        self.assertEqual(rep.error_breakdown["SyntaxError"], 1)
        self.assertEqual(rep.error_breakdown["AssertionError"], 1)
        self.assertEqual(rep.error_breakdown["NameError"], 1)
        for item in rep.details:
            self.assertIn("raw_output", item)
            self.assertEqual(item["raw_output"], outputs[next(t.prompt for t in tasks if t.task_id == item["task_id"])])
        self.assertEqual(_classify_failure(False, "timeout"), "timeout")
        self.assertEqual(_failure_breakdown(rep.details)["SyntaxError"], 1)

    def test_checkpoint_approval_is_fail_closed_on_gate_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "cand.pt"
            ckpt.write_bytes(b"weights")
            failed_decision = GateDecision(
                approved=False,
                reason="Candidate solved 0 unseen tasks in sandbox execution",
                baseline_unseen=0.0,
                candidate_unseen=0.0,
                baseline_regression=0.0,
                candidate_regression=0.0,
                leakage_count=0,
            )
            rec = record_checkpoint_approval(ckpt, "abc123", failed_decision)
            self.assertFalse(rec["approved"])
            self.assertEqual(rec["status"], "REJECTED_BY_GATE")
            self.assertIsNone(rec["approved_checkpoint"])

            tampered_decision = GateDecision(
                approved=True,
                reason="forced",
                baseline_unseen=0.0,
                candidate_unseen=0.0,
                baseline_regression=0.0,
                candidate_regression=0.0,
                leakage_count=0,
            )
            rec2 = record_checkpoint_approval(ckpt, "abc123", tampered_decision)
            self.assertFalse(rec2["approved"])
            self.assertIsNone(rec2["approved_checkpoint"])

    def test_multiseed_aggregation_rejects_partial_cherry_picked_pass(self) -> None:
        bd_pass = {"passed": 1, "SyntaxError": 0, "NameError": 0, "TypeError": 0, "AssertionError": 0, "timeout": 0, "other": 0}
        bd_fail = {"passed": 0, "SyntaxError": 1, "NameError": 0, "TypeError": 0, "AssertionError": 0, "timeout": 0, "other": 0}
        per_seed = [
            {
                "seed": 42,
                "results": {
                    "baseline_v1": {"reg_pass_rate": 0.0, "unseen_pass_rate": 0.0, "reg_loss": 2.0, "unseen_loss": 2.0, "reg_error_breakdown": bd_fail, "unseen_error_breakdown": bd_fail},
                    "candidate_v2_full": {"reg_pass_rate": 1.0, "unseen_pass_rate": 0.33, "reg_loss": 0.5, "unseen_loss": 1.1, "reg_error_breakdown": bd_pass, "unseen_error_breakdown": bd_pass, "approved": True, "approved_checkpoint": "/tmp/seed42.pt"},
                    "ablation_v2_no_resume_no_replay": {"reg_pass_rate": 0.0, "unseen_pass_rate": 0.0, "reg_loss": 1.5, "unseen_loss": 2.1, "reg_error_breakdown": bd_fail, "unseen_error_breakdown": bd_fail, "approved": False, "approved_checkpoint": None},
                },
            },
            {
                "seed": 1337,
                "results": {
                    "baseline_v1": {"reg_pass_rate": 0.0, "unseen_pass_rate": 0.0, "reg_loss": 2.0, "unseen_loss": 2.0, "reg_error_breakdown": bd_fail, "unseen_error_breakdown": bd_fail},
                    "candidate_v2_full": {"reg_pass_rate": 0.0, "unseen_pass_rate": 0.0, "reg_loss": 1.8, "unseen_loss": 2.3, "reg_error_breakdown": bd_fail, "unseen_error_breakdown": bd_fail, "approved": False, "approved_checkpoint": None},
                    "ablation_v2_no_resume_no_replay": {"reg_pass_rate": 0.0, "unseen_pass_rate": 0.0, "reg_loss": 1.9, "unseen_loss": 2.4, "reg_error_breakdown": bd_fail, "unseen_error_breakdown": bd_fail, "approved": False, "approved_checkpoint": None},
                },
            },
        ]
        agg = aggregate_multi_seed_runs(per_seed, leakage_count=0)
        cand = agg["candidate_v2_full"]
        self.assertEqual(cand["seeds_approved"], 1)
        self.assertEqual(cand["total_seeds"], 2)
        self.assertFalse(cand["overall_approved"])
        self.assertEqual(cand["approval_status"], "REJECTED_BY_GATE")
        self.assertEqual(cand["promoted_checkpoints"], [])

    def test_pure_multiseed_runners_execute_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            suite_rep = run_suite(out_dir=Path(tmpdir) / "suite", backend="pure", seeds=(42, 101))
            self.assertEqual(suite_rep["seeds"], [42, 101])
            self.assertEqual(len(suite_rep["per_seed_runs"]), 2)
            self.assertEqual(suite_rep["leakage_count"], 0)
            self.assertIn("raw_output", suite_rep["per_seed_runs"][0]["results"]["candidate_v2_full"]["unseen_details"][0])
            self.assertIn("SyntaxError", suite_rep["aggregate"]["candidate_v2_full"]["unseen_error_breakdown"])

            exp_rep = run_diverse_experiment(
                seeds=(42, 101),
                steps_p1=6,
                steps_p2=6,
                checkpoint_every=3,
                out_dir=Path(tmpdir) / "expanded",
                backend="pure",
            )
            self.assertEqual(exp_rep["seeds"], [42, 101])
            self.assertEqual(len(exp_rep["runs"]), 2)
            self.assertIn("all_seeds_approved", exp_rep["seed_summary"]["candidate_v2_full"])


if __name__ == "__main__":
    unittest.main()
