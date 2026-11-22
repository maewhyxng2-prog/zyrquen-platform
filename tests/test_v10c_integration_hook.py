"""V10-C integration tests for handle_training_execute, EvaluationEngine, and v10 CLI tools."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from apps.core.native.config import ZyrquenConfig
from apps.core.native.dataset import SCHEMA as DATASET_SCHEMA
from apps.core.native.evaluation import EvaluationEngine, EvaluationNotConfiguredError
from apps.core.native.sft import IGNORE_INDEX, SFT_FORMAT_VERSION, train_slot_safe_tokenizer
from apps.core.native.tokenizer import SCHEMA_V2
from apps.core.workflow.handlers.groups import handle_training_execute

REPO_ROOT = Path(__file__).resolve().parents[1]
HAS_TORCH = importlib.util.find_spec("torch") is not None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_valid_v10_dataset(root: Path) -> Path:
    tools_dir = str(REPO_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from gen_nagi_v10 import generate_dataset

    ds_dir = root / "nagi_v10"
    generate_dataset(ds_dir, seed=42, counts={"train": 24, "validation": 12, "test": 12})
    return ds_dir


class _FakeModel:
    pass


class TestV10CIntegrationHook(unittest.TestCase):
    def test_handle_training_execute_routes_sft_v10_and_binds_tokenizer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir = _make_valid_v10_dataset(root)
            train_rows = [json.loads(line) for line in (ds_dir / "train.jsonl").read_text().splitlines() if line.strip()]
            tok = train_slot_safe_tokenizer(train_rows, vocab_size=640, schema=SCHEMA_V2, use_slots=True)
            tok_path = root / "tokenizer.json"
            tok.save(tok_path)

            captured: dict = {}

            def fake_train_sft(
                model,
                train_pairs,
                val_pairs,
                cfg,
                checkpoint_dir,
                log_path,
                *,
                device="cpu",
                pad_id=0,
                tokenizer_fingerprint=None,
                dataset_version=None,
            ):
                captured["train_pairs"] = train_pairs
                captured["val_pairs"] = val_pairs
                captured["cfg"] = cfg
                captured["pad_id"] = pad_id
                captured["tokenizer_fingerprint"] = tokenizer_fingerprint
                captured["dataset_version"] = dataset_version
                return {
                    "steps": 4,
                    "stopped_reason": None,
                    "train_loss": 1.8,
                    "val_loss": 1.9,
                    "perplexity": 6.68,
                    "parameter_changed": True,
                    "prompt_format": SFT_FORMAT_VERSION,
                }

            res = handle_training_execute(
                {"consumed_approval": {"id": "app-1"}, "_train_fn": fake_train_sft, "_model": _FakeModel()},
                {
                    "dataset_dir": str(ds_dir),
                    "tokenizer_path": str(tok_path),
                    "checkpoint_dir": str(root / "ckpt"),
                    "batch_size": 2,
                    "max_steps": 4,
                    "block_size": 256,
                },
            )
            self.assertEqual(res.verdict, "PASS", res.summary)
            self.assertEqual(captured["tokenizer_fingerprint"], tok.fingerprint())
            self.assertEqual(captured["dataset_version"], "10.0.0")
            self.assertEqual(captured["pad_id"], tok.pad_id)
            self.assertEqual(len(captured["train_pairs"]), 24)
            self.assertEqual(len(captured["val_pairs"]), 12)
            first_x, first_y = captured["train_pairs"][0]
            self.assertEqual(first_x[0], tok.bos_id)
            self.assertIn(IGNORE_INDEX, first_y)
            self.assertEqual(res.output["prompt_format"], SFT_FORMAT_VERSION)

    def test_handle_training_execute_requires_approval_first(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            res = handle_training_execute({}, {"checkpoint_dir": td, "train_ids": [1, 2], "val_ids": [1, 2]})
            self.assertEqual(res.verdict, "NOT RUN")
            self.assertEqual(res.error_code, "approval_required")

    @unittest.skipIf(HAS_TORCH, "Verifies honest BLOCKED path when torch is absent")
    def test_handle_training_execute_blocks_honestly_without_torch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            res = handle_training_execute(
                {"consumed_approval": {"id": "app-1"}},
                {"checkpoint_dir": td, "train_ids": [1, 2], "val_ids": [1, 2]},
            )
            self.assertEqual(res.verdict, "BLOCKED")
            self.assertEqual(res.error_code, "torch_not_installed")

    def test_zyrquen_default_config_matches_v10_architecture(self) -> None:
        cfg = ZyrquenConfig()
        self.assertEqual(cfg.d_ff, 704)
        self.assertEqual(cfg.model_type, "zyrquen-decoder")
        self.assertLessEqual(cfg.validate_parameter_budget(), 5_000_000)

    def test_evaluation_engine_status_and_honest_not_configured(self) -> None:
        eng_unconfigured = EvaluationEngine()
        status_unconf = eng_unconfigured.get_status()
        self.assertEqual(status_unconf["status"], "not_configured")
        self.assertTrue(status_unconf["native_inference_evaluation_wired"])

        with tempfile.TemporaryDirectory() as td:
            eng = EvaluationEngine(Path(td))
            status_conf = eng.get_status()
            self.assertTrue(status_conf["checkpoint_dir_configured"])
            self.assertTrue(status_conf["native_inference_evaluation_wired"])
            self.assertEqual(status_conf["torch_installed"], HAS_TORCH)
            if not HAS_TORCH:
                self.assertEqual(status_conf["status"], "evidence_validation_only")
                with self.assertRaises(EvaluationNotConfiguredError):
                    eng.evaluate_native_model("v0.1.0", dataset_dir=td)

    def test_eval_nagi_v10_cli_reports_not_run_by_default_and_blocked_when_inference_requested_without_torch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir = _make_valid_v10_dataset(root)
            out_dir = root / "eval_out"

            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "eval_nagi_v10.py"),
                    "--dataset-dir",
                    str(ds_dir),
                    "--output-dir",
                    str(out_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            reports = list(out_dir.glob("v10_evaluation_*.json"))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(report["dataset_integrity"], "PASS")
            self.assertEqual(report["leakage_audit_status"], "PASS")
            self.assertEqual(report["inference_status"], "NOT RUN")
            self.assertEqual(report["overall_status"], "NOT RUN")
            self.assertTrue(report["inference_hook_implemented"])
            self.assertIsNone(report["metrics"])

            if not HAS_TORCH:
                proc_inf = subprocess.run(
                    [
                        sys.executable,
                        str(REPO_ROOT / "tools" / "eval_nagi_v10.py"),
                        "--dataset-dir",
                        str(ds_dir),
                        "--checkpoint-dir",
                        str(root / "ckpt"),
                        "--model-version",
                        "ZYRQUEN-Native-0.1.0",
                        "--run-inference",
                        "--no-write-report",
                    ],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(proc_inf.returncode, 3, proc_inf.stderr or proc_inf.stdout)
                self.assertIn("Inference: BLOCKED", proc_inf.stdout)
                self.assertIn("Overall: BLOCKED", proc_inf.stdout)

    def test_train_nagi_v10_cli_reports_wired_hook_and_never_starts_training(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir = _make_valid_v10_dataset(root)
            out_dir = root / "train_out"

            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "train_nagi_v10.py"),
                    "--dataset-dir",
                    str(ds_dir),
                    "--report-dir",
                    str(out_dir),
                    "--checkpoint-dir",
                    str(root / "ckpt"),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 3, proc.stderr or proc.stdout)
            reports = list(out_dir.glob("v10_training_preflight_*.json"))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertTrue(report["training_hook"]["implemented"])
            self.assertEqual(report["training_hook"]["status"], "wired_to_native_sft_hook")
            self.assertFalse(report["training_started"])
            self.assertFalse(report["checkpoint_created"])
            self.assertNotIn("TRAINING_HOOK_NOT_IMPLEMENTED", report["blockers"])
            self.assertTrue(
                "TIER2_HMAC_APPROVAL_REQUIRED" in report["blockers"]
                or "TIER2_APPROVAL_NOT_CONSUMED" in report["blockers"]
            )
            if not HAS_TORCH:
                self.assertIn("TORCH_NOT_INSTALLED", report["blockers"])


if __name__ == "__main__":
    unittest.main()
