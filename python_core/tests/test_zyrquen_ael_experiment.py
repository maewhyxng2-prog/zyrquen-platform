"""Unit and contract tests for ZYRQUEN Adaptive Experience-driven Learning (AEL) Experiment."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))

from v2.zyrquen_v2_trainer import CodingTask, EvalReport  # noqa: E402
from zyrquen_ael_experiment.ael_controller import (  # noqa: E402
    CONSOLIDATION_LAMBDA_BOUNDS,
    LR_SCALE_BOUNDS,
    REPLAY_RATIO_BOUNDS,
    RETRY_PRIORITY_BOUNDS,
    AdaptiveLearningController,
)
from zyrquen_ael_experiment.approval_gate import AELApprovalGate, compute_sha256  # noqa: E402
from zyrquen_ael_experiment.budget_controller import (  # noqa: E402
    BudgetController,
    BudgetExhaustedError,
    ComputeBudget,
)
from zyrquen_ael_experiment.experience_analyzer import ExperienceAnalyzer  # noqa: E402
from zyrquen_ael_experiment.experience_store import (  # noqa: E402
    ExperienceStore,
    SandboxExperienceRecord,
)
from zyrquen_ael_experiment.experiment import run_ael_experiment  # noqa: E402
from zyrquen_ael_experiment.sandbox_evaluator import (  # noqa: E402
    AELSandboxEvaluator,
    classify_sandbox_error,
)


def _rec(
    round_idx: int,
    split: str,
    task_id: str,
    fam: str,
    *,
    first_ok: bool,
    passed: bool,
    retries: int = 0,
    first_err: str = "passed",
    final_err: str = "passed",
) -> SandboxExperienceRecord:
    return SandboxExperienceRecord(
        round_idx=round_idx,
        split=split,
        task_id=task_id,
        task_family=fam,
        first_attempt_passed=first_ok,
        passed=passed,
        recovered_on_retry=(not first_ok) and passed,
        attempts_used=1 + retries,
        retries_used=retries,
        first_error_type=first_err,
        final_error_type=final_err,
        info="" if passed else final_err,
        raw_output="def f(x):\n    return x\n",
    )


class TestZyrquenAELExperiment(unittest.TestCase):
    def test_experience_store_rejects_heldout_feedback_fail_closed(self) -> None:
        store = ExperienceStore()
        for bad_split in ("heldout", "held_out", "unseen", "test"):
            with self.assertRaises(ValueError):
                store.add_round_records(
                    1,
                    [_rec(1, bad_split, "t_ho", "fam_a", first_ok=True, passed=True)],
                )
        added = store.add_round_records(
            1,
            [
                _rec(1, "train", "t1", "fam_a", first_ok=True, passed=True),
                _rec(1, "val", "v1", "fam_b", first_ok=False, passed=True, retries=1, first_err="AssertionError"),
            ],
        )
        self.assertEqual(added, 2)
        self.assertEqual(len(store.all_records()), 2)

    def test_analyzer_and_controller_adapt_with_bounds_and_audit_trail(self) -> None:
        store = ExperienceStore()
        analyzer = ExperienceAnalyzer(regression_drop_threshold=0.05)
        ctrl = AdaptiveLearningController(["fam_a", "fam_b", "fam_c"])

        # Round 1: fam_a strong (1.0), fam_b recovers via retry, fam_c fails with SyntaxError
        store.add_round_records(
            1,
            [
                _rec(1, "train", "a1", "fam_a", first_ok=True, passed=True),
                _rec(1, "val", "b1", "fam_b", first_ok=False, passed=True, retries=1, first_err="AssertionError"),
                _rec(1, "train", "c1", "fam_c", first_ok=False, passed=False, retries=1, first_err="SyntaxError", final_err="SyntaxError"),
            ],
        )
        a1 = analyzer.analyze(store, round_idx=1)
        changes1 = ctrl.update(a1)
        self.assertEqual(len(changes1), 5)
        self.assertAlmostEqual(sum(ctrl.state.task_priority.values()), 1.0, places=3)

        # Round 2: fam_a regresses sharply (1.0 -> 0.0), triggers replay + consolidation increase
        store.add_round_records(
            2,
            [
                _rec(2, "train", "a1", "fam_a", first_ok=False, passed=False, retries=1, first_err="SyntaxError", final_err="SyntaxError"),
                _rec(2, "train", "b1", "fam_b", first_ok=False, passed=False, retries=1, first_err="NameError", final_err="NameError"),
                _rec(2, "val", "c1", "fam_c", first_ok=False, passed=False, retries=1, first_err="SyntaxError", final_err="SyntaxError"),
            ],
        )
        a2 = analyzer.analyze(store, round_idx=2)
        self.assertIn("fam_a", a2.regressing_families)
        self.assertTrue(a2.family_signals["fam_a"].regressing)

        replay_before = ctrl.state.replay_ratio
        cons_before = ctrl.state.consolidation_lambda
        lr_before = ctrl.state.learning_rate_scale
        changes2 = ctrl.update(a2)

        self.assertGreater(ctrl.state.replay_ratio, replay_before)
        self.assertGreater(ctrl.state.consolidation_lambda, cons_before)
        self.assertLess(ctrl.state.learning_rate_scale, lr_before)
        self.assertTrue(REPLAY_RATIO_BOUNDS[0] <= ctrl.state.replay_ratio <= REPLAY_RATIO_BOUNDS[1])
        self.assertTrue(CONSOLIDATION_LAMBDA_BOUNDS[0] <= ctrl.state.consolidation_lambda <= CONSOLIDATION_LAMBDA_BOUNDS[1])
        self.assertTrue(RETRY_PRIORITY_BOUNDS[0] <= ctrl.state.retry_priority <= RETRY_PRIORITY_BOUNDS[1])
        self.assertTrue(LR_SCALE_BOUNDS[0] <= ctrl.state.learning_rate_scale <= LR_SCALE_BOUNDS[1])
        self.assertAlmostEqual(sum(ctrl.state.task_priority.values()), 1.0, places=3)
        for ch in changes2:
            self.assertTrue(ch.reason_code)
            self.assertIsInstance(ch.evidence, dict)

    def test_budget_controller_and_sandbox_evaluator_count_retries_in_budget(self) -> None:
        budget = ComputeBudget(
            max_training_steps=4,
            batch_size=2,
            max_sandbox_runs=3,
            max_attempts_per_task=2,
        )
        bc = BudgetController(budget, arm_name="test")
        bc.record_training_steps(4, 2)
        with self.assertRaises(BudgetExhaustedError):
            bc.record_training_steps(1, 2)

        def fake_gen(prompt: str) -> str:
            if "Self-Correction attempt 2" in prompt:
                return "def inc1(x):\n    return x + 1\n"
            return "def inc1(x):\n    return x - 1\n"

        ev = AELSandboxEvaluator(fake_gen, loss_fn=lambda _: 0.5, max_attempts=2)
        tasks = [
            CodingTask(
                task_id="t1",
                family="math",
                prompt="def inc1(x):\n    return ",
                test_code="assert inc1(2) == 3",
                reference_solution="def inc1(x):\n    return x + 1\n",
            ),
            CodingTask(
                task_id="t2",
                family="math",
                prompt="def inc2(x):\n    return ",
                test_code="assert inc2(2) == 4",
                reference_solution="def inc2(x):\n    return x + 2\n",
            ),
        ]
        first_rep, final_rep, recs = ev.evaluate(
            tasks, round_idx=1, split="val", budget=bc, retry_priority=1.0, count_in_budget=True
        )
        # Task 1 used 1st + retry = 2 runs; Task 2 used 1st = 1 run, retry blocked by max_sandbox_runs=3
        self.assertEqual(bc.sandbox_runs_used, 3)
        self.assertEqual(bc.first_pass_runs, 2)
        self.assertEqual(bc.retry_runs_used, 1)
        self.assertEqual(bc.retries_skipped_by_policy, 1)
        self.assertEqual(first_rep.passed_count, 0)
        self.assertEqual(final_rep.passed_count, 1)
        self.assertEqual(len(recs), 2)
        self.assertEqual(classify_sandbox_error(False, "SyntaxError: bad"), "SyntaxError")

    def test_approval_gate_verifies_sha256_and_budget_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt = Path(tmpdir) / "cand.json.gz"
            ckpt.write_bytes(b"weights")
            sha = compute_sha256(ckpt)
            gate = AELApprovalGate()

            base_ho = EvalReport(avg_loss=1.0, exec_pass_rate=0.0, passed_count=0, total_count=3)
            cand_ho = EvalReport(avg_loss=0.8, exec_pass_rate=0.3333, passed_count=1, total_count=3)
            base_val = EvalReport(avg_loss=1.0, exec_pass_rate=0.5, passed_count=1, total_count=2)
            cand_val = EvalReport(avg_loss=0.8, exec_pass_rate=0.5, passed_count=1, total_count=2)

            bad_sha = gate.verify_and_record(
                checkpoint_path=ckpt,
                expected_sha256="0" * 64,
                baseline_heldout=base_ho,
                candidate_heldout=cand_ho,
                baseline_val=base_val,
                candidate_val=cand_val,
                leakage_count=0,
                within_budget=True,
                metadata={"seed": 42},
            )
            self.assertFalse(bad_sha["approved"])
            self.assertEqual(bad_sha["status"], "REJECTED_BY_GATE")

            bad_budget = gate.verify_and_record(
                checkpoint_path=ckpt,
                expected_sha256=sha,
                baseline_heldout=base_ho,
                candidate_heldout=cand_ho,
                baseline_val=base_val,
                candidate_val=cand_val,
                leakage_count=0,
                within_budget=False,
                metadata={"seed": 42},
            )
            self.assertFalse(bad_budget["approved"])

            ok = gate.verify_and_record(
                checkpoint_path=ckpt,
                expected_sha256=sha,
                baseline_heldout=base_ho,
                candidate_heldout=cand_ho,
                baseline_val=base_val,
                candidate_val=cand_val,
                leakage_count=0,
                within_budget=True,
                metadata={"seed": 42},
            )
            self.assertTrue(ok["approved"])
            self.assertEqual(ok["status"], "APPROVED")

    def test_ael_experiment_pure_1seed_equal_budget_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            res = run_ael_experiment(
                seeds=(42,),
                backend="pure",
                pure_steps_per_stage=(1, 1, 1),
                batch_size=1,
                max_attempts_per_task=1,
                pure_max_new_tokens=6,
                reports_dir=tmpdir,
            )
            self.assertEqual(res["backend"], "pure_python_3.11_stdlib")
            self.assertFalse(res["external_models_used"])
            self.assertEqual(res["leakage_count"], 0)
            self.assertTrue(Path(res["report_json_path"]).is_file())
            self.assertTrue(Path(res["report_md_path"]).is_file())
            sr = res["seed_results"][0]
            self.assertEqual(
                sr["baseline"]["budget"]["training_steps_used"],
                sr["ael"]["budget"]["training_steps_used"],
            )
            self.assertTrue(sr["baseline"]["budget"]["within_sandbox_budget"])
            self.assertTrue(sr["ael"]["budget"]["within_sandbox_budget"])
            self.assertEqual(len(sr["ael"]["round_logs"]), 3)
            self.assertTrue(Path(sr["ael"]["experience_store_path"]).is_file())
            # Verify held-out never leaked into AEL experience store
            store_data = json.loads(Path(sr["ael"]["experience_store_path"]).read_text(encoding="utf-8"))
            for r in store_data["records"]:
                self.assertIn(r["split"], ("train", "val"))


if __name__ == "__main__":
    unittest.main()
