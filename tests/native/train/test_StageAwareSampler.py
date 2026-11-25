"""Comprehensive test suite for StageAwareSampler and governed native training workflow integration."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.core.native import train as train_module
from apps.core.native.dataset import PrepConfig, Source, prepare_dataset
from apps.core.native.train.StageAwareSampler import (
    StageAwareSampler,
    StageSamplerConfig,
    validate_stage_weights,
)
from apps.core.workflow import CentralWorkflowOrchestrator
from apps.core.workflow.handlers.groups import handle_training_execute


WORKFLOW_TRAINING_STAGES: tuple[str, ...] = (
    "provenance_leakage_gate",
    "baseline_verify",
    "approval_gate",
    "checkpoint_train",
    "checkpoint_eval_gate",
)


class StageAwareSamplerSuiteTests(unittest.TestCase):
    def test_resolves_b06_gap_and_package_exports(self) -> None:
        sampler_cls = getattr(train_module, "StageAwareSampler", None)
        self.assertIsNotNone(sampler_cls)
        self.assertIs(sampler_cls, StageAwareSampler)

    def test_invalid_stage_weights_rejected(self) -> None:
        records = [{"stage": "provenance_leakage_gate"}, {"stage": "checkpoint_train"}]
        bad_weight_cases = [
            {},
            [],
            "provenance_leakage_gate",
            {"": 1.0},
            {"   ": 1.0},
            {123: 1.0},
            {"provenance_leakage_gate": -0.01, "checkpoint_train": 1.0},
            {"provenance_leakage_gate": float("nan"), "checkpoint_train": 1.0},
            {"provenance_leakage_gate": float("inf"), "checkpoint_train": 1.0},
            {"provenance_leakage_gate": float("-inf"), "checkpoint_train": 1.0},
            {"provenance_leakage_gate": True, "checkpoint_train": 1.0},
            {"provenance_leakage_gate": False, "checkpoint_train": 1.0},
            {"provenance_leakage_gate": "0.5", "checkpoint_train": 0.5},
            {"provenance_leakage_gate": None, "checkpoint_train": 1.0},
            {"provenance_leakage_gate": 0.0, "checkpoint_train": 0.0},
        ]
        for bad_weights in bad_weight_cases:
            with self.subTest(bad_weights=bad_weights):
                with self.assertRaises(ValueError):
                    validate_stage_weights(bad_weights)  # type: ignore[arg-type]
                with self.assertRaises(ValueError):
                    StageAwareSampler(records, bad_weights)  # type: ignore[arg-type]

        # Positive-weight stage missing from dataset, and unconfigured dataset stage
        with self.assertRaises(ValueError):
            StageAwareSampler(
                records,
                {"provenance_leakage_gate": 0.5, "checkpoint_train": 0.3, "approval_gate": 0.2},
            )
        with self.assertRaises(ValueError):
            StageAwareSampler(records, {"provenance_leakage_gate": 1.0})

    def test_malformed_input_configurations_rejected(self) -> None:
        valid_records = [{"stage": st} for st in WORKFLOW_TRAINING_STAGES]
        valid_weights = {st: 0.2 for st in WORKFLOW_TRAINING_STAGES}

        malformed_datasets = [
            [],
            {},
            {"provenance_leakage_gate": []},
            None,
            "provenance_leakage_gate",
            b"bytes",
            True,
            0,
            -5,
            [{"text": "missing stage field"}],
            [{"stage": ""}],
            [{"stage": "   "}],
            [{"stage": 42}],
            {"provenance_leakage_gate": [-1]},
            {"provenance_leakage_gate": [True]},
            {"provenance_leakage_gate": [0, 1], "checkpoint_train": [1, 2]},
        ]
        for bad_ds in malformed_datasets:
            with self.subTest(bad_ds=bad_ds):
                with self.assertRaises(ValueError):
                    StageAwareSampler(bad_ds, valid_weights)  # type: ignore[arg-type]

        # Mismatched stages lengths and invalid parameter combinations
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, valid_weights, stages=["provenance_leakage_gate"])
        with self.assertRaises(ValueError):
            StageAwareSampler(len(valid_records), valid_weights, stages="abcde")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, valid_weights, seed=True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, valid_weights, seed="42")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, valid_weights, num_samples=0)
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, valid_weights, num_samples=True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, valid_weights, batch_size=0)
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, valid_weights, replacement="yes")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, valid_weights, drop_last=1)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, valid_weights, stage_key=" ")
        with self.assertRaises(ValueError):
            StageAwareSampler(valid_records, valid_weights, config={"seed": 1})  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            StageAwareSampler(
                valid_records,
                valid_weights,
                replacement=False,
                num_samples=len(valid_records) + 1,
            )

        # Atomic rejection during dynamic weight update and state restore
        sampler = StageAwareSampler(valid_records, valid_weights, seed=10)
        with self.assertRaises(ValueError):
            sampler.update_stage_weights({"provenance_leakage_gate": -1.0})
        self.assertEqual(sampler.stage_weights, valid_weights)
        with self.assertRaises(ValueError):
            sampler.load_state_dict(["not-a-dict"])  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            sampler.set_epoch(-1)

    def test_successful_sampling_across_all_workflow_stages(self) -> None:
        # Deliberately imbalanced pools across all 5 native_training workflow stages
        pool_sizes = {
            "provenance_leakage_gate": 80,
            "baseline_verify": 40,
            "approval_gate": 10,
            "checkpoint_train": 25,
            "checkpoint_eval_gate": 5,
        }
        records: list[dict[str, str]] = []
        for stage, count in pool_sizes.items():
            for i in range(count):
                records.append({"stage": stage, "text": f"{stage} sample {i}"})

        target_weights = {
            "provenance_leakage_gate": 0.15,
            "baseline_verify": 0.20,
            "approval_gate": 0.10,
            "checkpoint_train": 0.35,
            "checkpoint_eval_gate": 0.20,
        }

        sampler_a = StageAwareSampler(records, target_weights, seed=2026, num_samples=5000)
        sampler_b = StageAwareSampler(records, target_weights, seed=2026, num_samples=5000)
        sampler_c = StageAwareSampler(records, target_weights, seed=77, num_samples=5000)

        indices_a = list(sampler_a)
        indices_b = list(sampler_b)
        indices_c = list(sampler_c)

        self.assertEqual(len(indices_a), 5000)
        self.assertEqual(indices_a, indices_b)
        self.assertNotEqual(indices_a, indices_c)

        dist = sampler_a.measure_stage_distribution(indices_a)
        for stage, expected_prob in target_weights.items():
            self.assertAlmostEqual(dist[stage], expected_prob, delta=0.025)

        # Without replacement covers all records exactly once across all workflow stages
        no_rep = StageAwareSampler(
            records,
            target_weights,
            seed=2026,
            replacement=False,
            batch_size=32,
            drop_last=False,
        )
        all_unique = list(no_rep)
        self.assertEqual(len(all_unique), len(records))
        self.assertEqual(len(set(all_unique)), len(records))
        batched = [idx for batch in no_rep.sample_batches() for idx in batch]
        self.assertEqual(batched, all_unique)

        # Config factory parity
        cfg = StageSamplerConfig(stage_weights=target_weights, seed=2026, num_samples=200)
        from_cfg = StageAwareSampler.from_config(cfg, records)
        self.assertEqual(list(from_cfg), sampler_a.sample_indices(200))

    def test_workflow_handler_enforces_provenance_and_knowledge_quality(self) -> None:
        # 1. Disallowed provenance blocks execution
        blocked_prov = handle_training_execute(
            {
                "dataset_version": "v11.1.0",
                "provenance": "synthetic_llm_generated",
                "records": [{"text": "item 1", "stage": "checkpoint_train"}],
            }
        )
        self.assertEqual(blocked_prov["status"], "BLOCKED")
        self.assertFalse(blocked_prov["passed"])
        self.assertIn("PROVENANCE", blocked_prov["blocked_reason"])

        # 2. Unresolved knowledge contradictions block execution
        blocked_kq = handle_training_execute(
            {
                "dataset_version": "v11.1.0",
                "provenance": "curated_internal_corpus",
                "knowledge_quality": {
                    "status": "WARN",
                    "total_triples": 4,
                    "verified_triples": 2,
                    "provenance_coverage_pct": 100.0,
                    "contradiction_groups": 1,
                },
                "records": [{"text": "item 1", "stage": "checkpoint_train"}],
            }
        )
        self.assertEqual(blocked_kq["status"], "BLOCKED")
        self.assertFalse(blocked_kq["passed"])
        self.assertIn("KNOWLEDGE_QUALITY", blocked_kq["blocked_reason"])

        # 3. Filters out low-quality/contradictory/fake-provenance records and samples verified ones
        mixed_records = [
            {
                "text": "verified provenance doc 1",
                "stage": "provenance_leakage_gate",
                "provenance": "human_audited_docs",
                "quality_score": 0.95,
            },
            {
                "text": "verified provenance doc 2",
                "stage": "checkpoint_train",
                "provenance": "human_audited_docs",
                "quality_score": 0.90,
            },
            {
                "text": "verified eval doc 3",
                "stage": "checkpoint_eval_gate",
                "provenance": "human_audited_docs",
                "quality_score": 0.88,
            },
            {
                "text": "fake llm leak",
                "stage": "checkpoint_train",
                "provenance": "openai_gpt_export",
                "quality_score": 0.99,
            },
            {
                "text": "low confidence noise",
                "stage": "checkpoint_train",
                "provenance": "human_audited_docs",
                "quality_score": 0.30,
            },
            {
                "text": "contradictory claim",
                "stage": "checkpoint_eval_gate",
                "provenance": "human_audited_docs",
                "quality_score": 0.92,
                "contradiction": True,
            },
        ]
        res = handle_training_execute(
            {
                "dataset_version": "v11.1.0",
                "provenance": "human_audited_docs",
                "require_provenance": True,
                "leakage_verified": True,
                "knowledge_quality": {
                    "status": "VERIFIED",
                    "total_triples": 10,
                    "verified_triples": 10,
                    "provenance_coverage_pct": 100.0,
                    "contradiction_groups": 0,
                },
                "records": mixed_records,
                "stage_weights": {
                    "provenance_leakage_gate": 0.2,
                    "checkpoint_train": 0.5,
                    "checkpoint_eval_gate": 0.3,
                },
                "seed": 123,
                "num_samples": 1000,
            }
        )
        self.assertEqual(res["status"], "READY")
        self.assertTrue(res["passed"])
        self.assertFalse(res["external_models_used"])
        self.assertTrue(res["provenance_verified"])
        self.assertTrue(res["knowledge_quality_verified"])
        self.assertEqual(res["verified_record_count"], 3)
        self.assertEqual(res["rejected_record_count"], 3)
        self.assertEqual(res["sampler"]["class"], "StageAwareSampler")
        self.assertEqual(res["sampler"]["num_samples"], 1000)
        self.assertAlmostEqual(
            res["sampler"]["sampled_distribution"]["checkpoint_train"], 0.5, delta=0.05
        )

        # 4. Invalid stage_weights inside workflow handler fails cleanly
        bad_handler_cfg = handle_training_execute(
            {
                "dataset_version": "v11.1.0",
                "provenance": "human_audited_docs",
                "records": [
                    {"text": "doc", "stage": "checkpoint_train", "provenance": "human_audited_docs"}
                ],
                "stage_weights": {"checkpoint_train": -0.5},
            }
        )
        self.assertFalse(bad_handler_cfg["passed"])
        self.assertEqual(bad_handler_cfg["status"], "FAILED")

    def test_workflow_handler_reads_verified_manifest_dataset_and_registers_in_orchestrator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_file = tmp_path / "corpus.jsonl"
            rows = [
                {
                    "text": f"Native ZYRQUEN verified architecture sample number {i} for stage training."
                }
                for i in range(40)
            ]
            src_file.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                encoding="utf-8",
            )
            ds_dir = tmp_path / "ds"
            prepare_dataset(
                [Source(str(src_file), "MIT-declared", "core")],
                ds_dir,
                PrepConfig(val_fraction=0.1, test_fraction=0.1, version="1.0.0"),
            )

            res = handle_training_execute(
                {
                    "dataset_version": "v10.0.0",
                    "dataset_dir": str(ds_dir),
                    "split": "train",
                    "provenance": "verified_native_corpus",
                    "require_provenance": True,
                    "seed": 9,
                    "num_samples": 12,
                }
            )
            self.assertEqual(res["status"], "READY")
            self.assertTrue(res["passed"])
            self.assertEqual(res["sampler"]["class"], "StageAwareSampler")
            self.assertEqual(res["sampler"]["num_samples"], 12)

            orch = CentralWorkflowOrchestrator(
                db_path=tmp_path / "wf.db",
                work_dir=tmp_path / "wf-work",
                approval_secret="test-secret-key-for-workflow-sampler-32chars",
            )
            try:
                handler = orch.registry.get_handler("training.execute")
                self.assertIs(handler, handle_training_execute)
            finally:
                orch.shutdown(wait=True)

    def test_zyrquen_core_native_training_integrates_stage_aware_sampler(self) -> None:
        py_core_dir = str(REPO_ROOT / "python_core")
        if py_core_dir not in sys.path:
            sys.path.insert(0, py_core_dir)
        import zyrquen_core as zc

        orig_data = zc.DATA_DIR
        orig_ckpt = zc.CHECKPOINT_DIR
        orig_db = zc.DB_PATH
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zc.DATA_DIR = tmp_path
            zc.CHECKPOINT_DIR = tmp_path / "checkpoints"
            zc.DB_PATH = tmp_path / "zyrquen_test.db"
            zc.init_db()
            try:
                # Seed a verified triple + a conflicting triple pair
                conn = zc.get_db()
                with conn:
                    conn.execute(
                        "INSERT INTO knowledge_triples (id, subject, relation, object, source, confidence, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        ("t1", "AlphaEngine", "uses", "NativeWeights", "verified_audit_doc", 0.95, "tester", zc.now_iso()),
                    )
                    conn.execute(
                        "INSERT INTO knowledge_triples (id, subject, relation, object, source, confidence, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        ("t2", "BetaFlag", "state", "enabled", "uncorroborated_note", 0.40, "tester", zc.now_iso()),
                    )
                conn.close()

                corpus = "\n".join([
                    "astronomy telescope mirror calibration optical clarity",
                    "botany photosynthesis chloroplast pigment chlorophyll sunlight",
                    "chemistry covalent molecular orbitals valence electron shells",
                    "geology sedimentary limestone fossil strata tectonic subduction",
                    "hydrology watershed aquifer precipitation drainage basin",
                    "mechanics pendulum angular momentum rotational inertia torque",
                    "acoustics resonance harmonic frequency waveform vibration",
                    "metallurgy crystal lattice annealing alloy hardness tempering",
                    "thermodynamics entropy enthalpy Carnot efficiency heat engine",
                    "optics refraction Snell prism dispersion chromatic spectrum",
                    "cartography projection meridian latitude contour elevation",
                    "robotics kinematics actuator feedback encoder PID controller",
                ])
                ds_res = zc.handle_ingest_dataset(
                    {
                        "name": "verified-sampler-corpus",
                        "content": corpus,
                        "provenance": "human_curated_native_corpus",
                        "user_id": "tester",
                    }
                )
                self.assertTrue(ds_res.get("ok"), ds_res)
                conn = zc.get_db()
                train_res = zc.train_checkpoint_from_dataset(conn, ds_res["dataset"]["id"], "tester")
                conn.close()

                self.assertTrue(train_res["ok"], train_res.get("error"))
                self.assertEqual(train_res["sampling"]["sampler"], "StageAwareSampler")
                self.assertIn("verified_dataset", train_res["sampling"]["stage_counts"])
                self.assertIn("verified_knowledge", train_res["sampling"]["stage_counts"])
                # Uncorroborated low-confidence triple t2 must not be ingested into verified_knowledge
                self.assertEqual(train_res["sampling"]["stage_counts"]["verified_knowledge"], 1)
            finally:
                zc.DATA_DIR = orig_data
                zc.CHECKPOINT_DIR = orig_ckpt
                zc.DB_PATH = orig_db


if __name__ == "__main__":
    unittest.main()
