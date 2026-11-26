"""
Unit & Integration Tests for:
1. ZYRQUEN REAL-ONLY Training Worker v1.1 (`real_only_trainer.py`)
2. Continuous NativeTransformerLM Checkpoint Continuation (`code_problem_training.py`)
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))

import code_problem_training as cpt  # noqa: E402
import memory_learning as ml  # noqa: E402
import real_only_trainer as rot  # noqa: E402
import zyrquen_core as zc  # noqa: E402
from tests.benchmark_suite import isolated_core_env  # noqa: E402


def _write_real_jsonl(path: Path, count_per_class: int = 18) -> None:
    lines: list[str] = []
    # Class 1: guarded functions with branch / try-except / return checks
    for idx in range(count_per_class):
        code = (
            f"def guarded_op_{idx}(x, y):\n"
            f"    if y == 0:\n"
            f"        return 0\n"
            f"    try:\n"
            f"        return x / (y + {idx})\n"
            f"    except ZeroDivisionError:\n"
            f"        return 0\n"
        )
        lines.append(json.dumps({"code": code, "label": 1, "source": "internal_ast_verified"}))
    # Class 0: unguarded raw expressions without branch or exception safety
    for idx in range(count_per_class):
        code = f"val_{idx} = {idx + 1} + {idx + 2}\n"
        lines.append(json.dumps({"code": code, "label": 0, "source": "internal_ast_verified"}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class RealOnlyAndContinuationTests(unittest.TestCase):
    def test_real_only_worker_stops_fail_closed_without_real_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            missing_res = rot.run_real_only_training(
                data_path=tmp_path / "does_not_exist.jsonl",
                out_dir=tmp_path / "out_missing",
            )
            self.assertFalse(missing_res["ok"])
            self.assertEqual(missing_res["status"], "BLOCKED")
            self.assertEqual(missing_res["reason"], "MISSING_DATA_FILE")
            self.assertFalse((tmp_path / "out_missing" / "checkpoint.json").exists())

            small_jsonl = tmp_path / "too_small.jsonl"
            _write_real_jsonl(small_jsonl, count_per_class=5)  # 10 rows < 30
            small_res = rot.run_real_only_training(
                data_path=small_jsonl,
                out_dir=tmp_path / "out_small",
                min_samples=30,
            )
            self.assertFalse(small_res["ok"])
            self.assertEqual(small_res["status"], "BLOCKED")
            self.assertEqual(small_res["reason"], "INSUFFICIENT_REAL_DATA")
            self.assertFalse((tmp_path / "out_small" / "checkpoint.json").exists())

    def test_real_only_worker_rejects_synthetic_provenance_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            jsonl_path = tmp_path / "real_corpus.jsonl"
            _write_real_jsonl(jsonl_path, count_per_class=18)  # 36 valid unique rows
            # Append a disallowed external LLM entry and a syntax-error entry
            with jsonl_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"code": "def f(): return 1", "label": 1, "provenance": "synthetic_gpt"}) + "\n")
                fh.write(json.dumps({"code": "def broken(:", "label": 0}) + "\n")

            out_dir = tmp_path / "artifacts"
            res1 = rot.run_real_only_training(
                data_path=jsonl_path,
                out_dir=out_dir,
                epochs=12,
                lr=0.1,
                seed=42,
            )
            self.assertTrue(res1["ok"], res1)
            self.assertEqual(res1["leak_count"], 0)
            self.assertFalse(res1["external_models_used"])
            self.assertFalse(res1["synthetic_data_used"])
            self.assertEqual(res1["dataset_summary"]["rejected_stats"]["disallowed_provenance"], 1)
            self.assertEqual(res1["dataset_summary"]["rejected_stats"]["syntax_error"], 1)
            self.assertTrue(res1["improved"])
            self.assertEqual(res1["approval"], "PENDING_APPROVAL")
            ckpt1 = Path(res1["checkpoint_path"])
            self.assertTrue(ckpt1.exists())
            ckpt1_bytes = ckpt1.read_bytes()

            # Second run targeting same out_dir must NOT overwrite ckpt1
            res2 = rot.run_real_only_training(
                data_path=jsonl_path,
                out_dir=out_dir,
                epochs=12,
                lr=0.1,
                seed=7,
            )
            self.assertTrue(res2["ok"])
            ckpt2 = Path(res2["checkpoint_path"])
            self.assertNotEqual(ckpt1, ckpt2)
            self.assertTrue(ckpt2.exists())
            self.assertEqual(ckpt1.read_bytes(), ckpt1_bytes)

    def test_code_problem_experiment_continues_from_approved_checkpoint_weights(self) -> None:
        with isolated_core_env():
            conn = zc.get_db()
            curated = cpt.curate_code_problem_corpus(
                conn,
                "admin-test",
                zc.handle_ingest_dataset,
                name="code-continuation-corpus",
            )
            self.assertTrue(curated["ok"], curated)
            ds_id = curated["dataset"]["id"]

            # Round 1: Random init -> PENDING_APPROVAL -> Admin approves to create v1
            round1 = cpt.run_code_problem_experiment(
                conn,
                zc.CHECKPOINT_DIR,
                "admin-test",
                dataset_id=ds_id,
                epochs=3,
                seed=42,
            )
            self.assertTrue(round1["ok"], round1)
            self.assertEqual(round1["metrics"]["training_mode"], "random_init")
            self.assertIsNone(round1["metrics"]["continued_from_checkpoint_version"])
            self.assertEqual(round1["experiment"]["approval_status"], "PENDING_APPROVAL")

            dec1 = ml.decide_experiment(
                conn,
                zc.CHECKPOINT_DIR,
                experiment_id=round1["experiment"]["id"],
                decision="approve",
                admin_email="admin@zyrquen.local",
                admin_id="admin-test",
            )
            self.assertTrue(dec1["ok"], dec1)
            v1_ckpt = dec1["checkpoint"]
            self.assertEqual(int(v1_ckpt["version"]), 1)
            v1_path = Path(v1_ckpt["weights_path"])
            self.assertTrue(v1_path.exists())
            v1_bytes = v1_path.read_bytes()

            # Round 2: Must load v1 weights, measure pre/post unseen loss, and update weights genuinely
            round2 = cpt.run_code_problem_experiment(
                conn,
                zc.CHECKPOINT_DIR,
                "admin-test",
                dataset_id=ds_id,
                epochs=3,
                seed=43,
            )
            self.assertTrue(round2["ok"], round2)
            self.assertEqual(round2["metrics"]["training_mode"], "checkpoint_continuation")
            self.assertEqual(round2["metrics"]["continued_from_checkpoint_version"], 1)
            self.assertGreater(float(round2["metrics"]["param_drift_rms"] or 0.0), 0.0)
            self.assertIn("initial_test_loss", round2["metrics"])
            self.assertIn("test_loss", round2["metrics"])

            if round2["experiment"]["approval_status"] == "PENDING_APPROVAL":
                dec2 = ml.decide_experiment(
                    conn,
                    zc.CHECKPOINT_DIR,
                    experiment_id=round2["experiment"]["id"],
                    decision="approve",
                    admin_email="admin@zyrquen.local",
                    admin_id="admin-test",
                )
                self.assertTrue(dec2["ok"], dec2)
                v2_ckpt = dec2["checkpoint"]
                self.assertEqual(int(v2_ckpt["version"]), 2)
                self.assertTrue(Path(v2_ckpt["weights_path"]).exists())
                # v1 checkpoint file preserved untouched
                self.assertEqual(v1_path.read_bytes(), v1_bytes)
            conn.close()


if __name__ == "__main__":
    unittest.main()
