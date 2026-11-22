"""Pure-Python static & helper contract tests for tools/train_nagi_v9.py and tools/eval_nagi_v9.py.

Does NOT require PyTorch, does NOT touch data/nagi_v9/, and does NOT fabricate
training runs, model weights, or benchmark PASS claims.
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import eval_nagi_v9 as e9  # noqa: E402
import train_nagi_v9 as t9  # noqa: E402


class TestTrainV9PureHelpers(unittest.TestCase):
    def test_build_vocab_and_el05_zero_leakage(self) -> None:
        train_rows = [
            {"input": "rel: TR_E001 > TR_E002 , TR_E002 > TR_E003 | query TR_E001 ? TR_E003", "target": ">"},
            {"input": "facts: TR_E004 -> TR_E005 | lookup TR_E004 ?", "target": "TR_E005"},
        ]
        eval_rows = [
            {"input": "rel: VA_E001 > VA_E002 , VA_E002 > VA_E003 | query VA_E001 ? VA_E003", "target": ">"},
            {"input": "facts: TE_E001 -> TE_E002 | lookup TE_E001 ?", "target": "TE_E002"},
        ]

        vocab_slots = t9.build_vocab(train_rows, use_slots=True)
        # Slots reserve <slot_0..31>; train entities never enter static slot vocab
        self.assertIn("<slot_0>", vocab_slots)
        self.assertIn("<slot_31>", vocab_slots)
        self.assertNotIn("TR_E001", vocab_slots)
        ok_s, ov_s = t9.verify_vocab_no_eval_leakage(vocab_slots, eval_rows)
        self.assertTrue(ok_s)
        self.assertEqual(ov_s, [])

        vocab_std = t9.build_vocab(train_rows, use_slots=False)
        self.assertIn("TR_E001", vocab_std)
        ok_std, ov_std = t9.verify_vocab_no_eval_leakage(vocab_std, eval_rows)
        self.assertTrue(ok_std)
        self.assertEqual(ov_std, [])

        # Simulate leaked eval entity in vocab -> EL-05 check must catch & block it
        leaked_ok, leaked_list = t9.verify_vocab_no_eval_leakage(vocab_std + ["TE_E002"], eval_rows)
        self.assertFalse(leaked_ok)
        self.assertEqual(leaked_list, ["TE_E002"])

    def test_slotted_binding_equivariance_and_surface_roundtrip(self) -> None:
        train_rows = [
            {"input": "rel: TR_E001 > TR_E002 , TR_E002 > TR_E003 | query TR_E001 ? TR_E003", "target": ">"},
            {"input": "facts: TR_E001 -> TR_E002 | lookup TR_E001 ?", "target": "TR_E002"},
        ]
        vocab = t9.build_vocab(train_rows, use_slots=True)
        stoi = {tok: i for i, tok in enumerate(vocab)}

        inp = "facts: TE_E010 -> TE_E020 ; TE_E030 -> TE_E040 | lookup TE_E010 ?"
        tgt = "TE_E020"
        enc = t9.encode_pair_slotted(inp, tgt, stoi, max_seq=256, permute_slots=True, rng=random.Random(7))
        self.assertIsNotNone(enc)
        src_ids, trg_ids, binding = enc  # type: ignore[misc]

        # Reoccurring entity TE_E010 maps to the same slot token everywhere
        slot_e10 = binding.surface_to_slot["TE_E010"]
        slot_e20 = binding.surface_to_slot["TE_E020"]
        self.assertNotEqual(slot_e10, slot_e20)
        self.assertEqual(src_ids.count(stoi[slot_e10]), 2)
        self.assertEqual(trg_ids, [t9.BOS_ID, stoi[slot_e20], t9.EOS_ID])
        self.assertEqual(binding.slot_to_surface[slot_e20], "TE_E020")

    def test_make_stratified_batches_deterministic(self) -> None:
        rows = [{"id": f"r-{i}"} for i in range(10)]
        b1 = t9.make_stratified_batches(rows, batch_size=4, total_steps=6, seed=42)
        b2 = t9.make_stratified_batches(rows, batch_size=4, total_steps=6, seed=42)
        self.assertEqual(b1, b2)
        self.assertEqual(len(b1), 6)
        self.assertTrue(all(len(b) == 4 for b in b1))

    def test_collect_runtime_environment_pure_python(self) -> None:
        env = t9.collect_runtime_environment(None, None)
        self.assertIn("python_version", env)
        self.assertIn("platform", env)
        self.assertIsNotNone(env["cpu_count"])
        self.assertFalse(env["cuda_available"])
        self.assertIsNone(env["torch_version"])
        self.assertIsNone(env["gpu_name"])


class TestEvalV9PureHelpers(unittest.TestCase):
    def test_calc_repetition_patterns(self) -> None:
        self.assertFalse(e9.calc_repetition(["TE_E001"]))
        self.assertFalse(e9.calc_repetition(["TE_E001", "->", "TE_E002", "->", "TE_E003"]))
        self.assertTrue(e9.calc_repetition(["TE_E001", "TE_E001"]))
        self.assertTrue(e9.calc_repetition(["true", "true", "true"]))
        self.assertTrue(e9.calc_repetition(["TE_E001", "->", "TE_E001", "->"]))

    def test_permute_premises_safe_changes_order_preserving_clauses(self) -> None:
        row = {
            "capability": "relational_reasoning",
            "template_id": "RR_TR_01",
            "input": "rel: TE_E001 > TE_E002 , TE_E002 > TE_E003 , TE_E004 > TE_E005 | query TE_E001 ? TE_E003",
            "target": ">",
        }
        perm = e9._permute_premises_safe(row, random.Random(123))
        self.assertIsNotNone(perm)
        assert perm is not None
        self.assertNotEqual(perm, row["input"])
        self.assertTrue(perm.endswith("| query TE_E001 ? TE_E003"))
        self.assertIn("TE_E001 > TE_E002", perm)
        self.assertIn("TE_E002 > TE_E003", perm)

    def test_acceptance_assessment_and_stop_triggers(self) -> None:
        def make_split(fg_exact: float, copy_acc: float | None, rep: float, eos: float, pgen_reason: float) -> dict:
            per_cap = {
                cap: {
                    "count": 15,
                    "teacher_forced": {"exact_match": fg_exact + 0.02},
                    "free_generation": {"exact_match": fg_exact},
                }
                for cap in e9.EXPECTED_CAPABILITIES
            }
            return {
                "overall": {
                    "count": 120,
                    "teacher_forced": {"exact_match": fg_exact + 0.02},
                    "free_generation": {
                        "exact_match": fg_exact,
                        "unseen_entity_copy_acc": copy_acc,
                        "unseen_entity_reasoning_acc": 0.80,
                        "eos_hit_rate": eos,
                        "premature_eos_rate": 0.0,
                        "repetition_rate": rep,
                        "adaptive_override_acc": 0.80,
                        "adaptive_retention_acc": 0.90,
                        "conflict_detection_f1": 0.85,
                        "plan_validity_acc": 0.80,
                        "impossible_plan_acc": 0.80,
                        "verification_acc": 0.80,
                        "multi_hop_acc": {"1_hop": 0.9, "2_to_3_hop": 0.85, "4_plus_hop": 0.72},
                        "copy_tasks_mean_p_gen": 0.25,
                        "reasoning_tasks_mean_p_gen": pgen_reason,
                        "verdict_majority_collapse_share": 0.30,
                    },
                    "exposure_bias_gap": 0.02,
                },
                "per_capability": per_cap,
            }

        splits = {
            "val_unseen": make_split(0.84, 0.90, 0.01, 0.99, 0.75),
            "val_ood": make_split(0.76, 0.88, 0.01, 0.99, 0.75),
            "test_unseen": make_split(0.85, 0.90, 0.01, 0.99, 0.75),
            "test_ood": make_split(0.75, 0.88, 0.01, 0.99, 0.75),
        }
        probes = {
            "probe_2_premise_permutation_invariance": {"passed": True},
            "probe_3_depth_extrapolation_gap": {"passed": True},
            "probe_4_distractor_sensitivity": {"passed": True},
            "probe_6_pointer_gate_discipline": {
                "copy_tasks_mean_p_gen": 0.25,
                "reasoning_tasks_mean_p_gen": 0.75,
                "passed": True,
            },
        }
        assess = e9.assess_acceptance_and_stop_criteria(
            "arm_d", {"params": 1_200_000}, splits, probes, baseline_reports=[]
        )
        self.assertEqual(assess["stop_criteria_triggered"], [])
        self.assertEqual(assess["criteria"]["unseen_entity_copy_ge_0.85"]["status"], "PASS")
        self.assertEqual(assess["criteria"]["beats_baselines_ood_by_5pp"]["status"], "PENDING_COMPARISON")

        # Degenerate split must trigger stop criteria honestly
        bad_splits = dict(splits)
        bad_splits["test_unseen"] = make_split(0.20, None, 0.25, 0.70, 0.10)
        bad_splits["test_ood"] = make_split(0.15, None, 0.25, 0.70, 0.10)
        bad_probes = dict(probes)
        bad_probes["probe_6_pointer_gate_discipline"] = {
            "copy_tasks_mean_p_gen": 0.05,
            "reasoning_tasks_mean_p_gen": 0.10,
            "passed": False,
        }
        bad_assess = e9.assess_acceptance_and_stop_criteria(
            "arm_c", {"params": 523_708}, bad_splits, bad_probes, baseline_reports=[]
        )
        self.assertGreaterEqual(len(bad_assess["stop_criteria_triggered"]), 4)


if __name__ == "__main__":
    unittest.main()
