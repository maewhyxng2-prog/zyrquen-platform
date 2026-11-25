"""Unit and statistical tests for StageAwareSampler (B-06)."""

from __future__ import annotations

import math
import unittest
from dataclasses import dataclass

from apps.core.native import train as train_module
from apps.core.native.train import StageAwareSampler as PackageSampler
from apps.core.native.train.StageAwareSampler import (
    StageAwareSampler,
    StageSamplerConfig,
    validate_stage_weights,
)


@dataclass
class _RecordObj:
    text: str
    stage: str


class StageAwareSamplerTests(unittest.TestCase):
    def test_import_surface_resolves_b06_gap(self) -> None:
        sampler_cls = getattr(train_module, "StageAwareSampler", None)
        self.assertIsNotNone(sampler_cls)
        self.assertIs(sampler_cls, StageAwareSampler)
        self.assertIs(PackageSampler, StageAwareSampler)

    def test_stage_sampler_is_deterministic_for_same_seed(self) -> None:
        records = (
            [{"text": f"f-{i}", "stage": "foundation"} for i in range(40)]
            + [{"text": f"r-{i}", "stage": "reasoning"} for i in range(15)]
            + [{"text": f"v-{i}", "stage": "verification"} for i in range(5)]
        )
        weights = {"foundation": 0.5, "reasoning": 0.3, "verification": 0.2}

        s1 = StageAwareSampler(records, weights, seed=1337, num_samples=250)
        s2 = StageAwareSampler(records, weights, seed=1337, num_samples=250)
        s3 = StageAwareSampler(records, weights, seed=9999, num_samples=250)

        seq1 = list(s1)
        seq2 = list(s2)
        seq3 = list(s3)

        self.assertEqual(len(seq1), 250)
        self.assertEqual(seq1, seq2)
        self.assertNotEqual(seq1, seq3)

        s1.set_epoch(3)
        s2.set_epoch(3)
        self.assertEqual(s1.sample_indices(100), s2.sample_indices(100))
        self.assertNotEqual(s1.sample_indices(100, epoch=0), s1.sample_indices(100, epoch=3))

    def test_stage_sampler_respects_stage_weights_statistically(self) -> None:
        # Deliberately imbalanced dataset: foundation=200, reasoning=10, verification=5
        records = (
            [{"id": i, "stage": "foundation"} for i in range(200)]
            + [{"id": 200 + i, "stage": "reasoning"} for i in range(10)]
            + [{"id": 210 + i, "stage": "verification"} for i in range(5)]
        )
        # Unnormalized weights -> normalized: 0.2, 0.5, 0.3
        sampler = StageAwareSampler(
            records,
            stage_weights={"foundation": 2.0, "reasoning": 5.0, "verification": 3.0},
            seed=42,
            num_samples=6000,
        )
        norm = sampler.normalized_weights
        self.assertAlmostEqual(norm["foundation"], 0.2, places=9)
        self.assertAlmostEqual(norm["reasoning"], 0.5, places=9)
        self.assertAlmostEqual(norm["verification"], 0.3, places=9)

        drawn = list(sampler)
        empirical = sampler.measure_stage_distribution(drawn)
        self.assertAlmostEqual(empirical["foundation"], 0.2, delta=0.025)
        self.assertAlmostEqual(empirical["reasoning"], 0.5, delta=0.025)
        self.assertAlmostEqual(empirical["verification"], 0.3, delta=0.025)

    def test_zero_weight_stage_is_never_sampled(self) -> None:
        records = (
            [{"stage": "active_a"} for _ in range(20)]
            + [{"stage": "disabled"} for _ in range(50)]
            + [{"stage": "active_b"} for _ in range(20)]
        )
        sampler = StageAwareSampler(
            records,
            {"active_a": 0.75, "disabled": 0.0, "active_b": 0.25},
            seed=7,
            num_samples=1000,
        )
        indices = list(sampler)
        dist = sampler.measure_stage_distribution(indices)
        self.assertEqual(dist["disabled"], 0.0)
        self.assertAlmostEqual(dist["active_a"], 0.75, delta=0.04)
        self.assertAlmostEqual(dist["active_b"], 0.25, delta=0.04)

    def test_without_replacement_and_batch_generation(self) -> None:
        stage_map = {
            "s1": [0, 1, 2, 3, 4],
            "s2": [5, 6, 7, 8, 9],
        }
        sampler = StageAwareSampler(
            stage_map,
            {"s1": 0.8, "s2": 0.2},
            seed=11,
            replacement=False,
            batch_size=4,
            drop_last=True,
        )
        full = list(sampler)
        self.assertEqual(len(full), 10)
        self.assertEqual(len(set(full)), 10)
        self.assertEqual(set(full), set(range(10)))

        batches = list(sampler.sample_batches())
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[0] + batches[1], full[:8])

    def test_input_format_variants_and_config_factory(self) -> None:
        objs = [_RecordObj(text=f"x{i}", stage="a" if i < 4 else "b") for i in range(10)]
        cfg = StageSamplerConfig(stage_weights={"a": 0.4, "b": 0.6}, seed=5, num_samples=20)
        s_cfg = StageAwareSampler.from_config(cfg, objs)
        self.assertEqual(len(s_cfg), 20)

        s_int = StageAwareSampler(6, {"x": 0.5, "y": 0.5}, stages=["x", "x", "x", "y", "y", "y"], seed=5)
        self.assertEqual(s_int.stage_counts, {"x": 3, "y": 3})

        s_labels = StageAwareSampler(["p", "p", "q", "q"], weights={"p": 1, "q": 3}, seed=5)
        self.assertEqual(s_labels.normalized_weights, {"p": 0.25, "q": 0.75})

    def test_dynamic_weight_update_and_checkpoint_state_roundtrip(self) -> None:
        records = [{"stage": "s1"} for _ in range(30)] + [{"stage": "s2"} for _ in range(30)]
        sampler = StageAwareSampler(records, {"s1": 0.9, "s2": 0.1}, seed=21, num_samples=2000)

        dist_before = sampler.measure_stage_distribution(list(sampler))
        self.assertGreater(dist_before["s1"], 0.85)

        # Invalid update must fail atomically without mutating existing weights
        with self.assertRaises(ValueError):
            sampler.update_stage_weights({"s1": -1.0, "s2": 1.0})
        self.assertAlmostEqual(sampler.normalized_weights["s1"], 0.9, places=9)

        sampler.update_stage_weights({"s1": 0.1, "s2": 0.9})
        dist_after = sampler.measure_stage_distribution(list(sampler))
        self.assertGreater(dist_after["s2"], 0.85)

        saved = sampler.state_dict()
        restored = StageAwareSampler(records, {"s1": 0.5, "s2": 0.5}, seed=0, num_samples=100)
        restored.load_state_dict(saved)
        self.assertEqual(list(sampler), list(restored))

    def test_configuration_validation_rejects_invalid_inputs(self) -> None:
        valid_records = [{"stage": "a"}, {"stage": "b"}]

        # Invalid stage_weights maps
        for bad_weights in (
            {},
            {"": 1.0},
            {"   ": 1.0},
            {"a": -0.5, "b": 1.0},
            {"a": float("nan"), "b": 1.0},
            {"a": float("inf"), "b": 1.0},
            {"a": True, "b": 1.0},
            {"a": "0.5", "b": 0.5},
            {"a": 0.0, "b": 0.0},
        ):
            with self.subTest(bad_weights=bad_weights):
                with self.assertRaises(ValueError):
                    validate_stage_weights(bad_weights)  # type: ignore[arg-type]
                with self.assertRaises(ValueError):
                    StageAwareSampler(valid_records, bad_weights)  # type: ignore[arg-type]

        # Empty or malformed datasets
        for bad_data in ([], {}, {"a": []}, "ab", True, 0):
            with self.subTest(bad_data=bad_data):
                with self.assertRaises(ValueError):
                    StageAwareSampler(bad_data, {"a": 1.0})  # type: ignore[arg-type]

        # Mismatched stages / missing fields / duplicate mapping indices
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, {"a": 1.0}, stages=["a"])
        with self.assertRaises(ValueError):
            StageAwareSampler([{"text": "missing stage"}], {"a": 1.0})
        with self.assertRaises(ValueError):
            StageAwareSampler({"a": [0, 1], "b": [1, 2]}, {"a": 0.5, "b": 0.5})

        # Unconfigured dataset stage & empty positive-weight stage
        with self.assertRaises(ValueError):
            StageAwareSampler([{"stage": "a"}, {"stage": "unknown"}], {"a": 1.0})
        with self.assertRaises(ValueError):
            StageAwareSampler([{"stage": "a"}], {"a": 0.5, "missing_bucket": 0.5})

        # Invalid sampling parameters
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, {"a": 0.5, "b": 0.5}, seed=True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, {"a": 0.5, "b": 0.5}, num_samples=0)
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, {"a": 0.5, "b": 0.5}, batch_size=0)
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, {"a": 0.5, "b": 0.5}, replacement=False, num_samples=3)


if __name__ == "__main__":
    unittest.main()
