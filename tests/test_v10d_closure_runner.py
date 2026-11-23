"""Tests for tools/close_v10d.py end-to-end V10-D closure pipeline runner."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from apps.core.native.checkpoint import CheckpointManager
from apps.core.native.registry import ModelRegistry
from apps.core.native.sft import SFT_FORMAT_VERSION
from close_v10d import CLOSURE_RUNNER_SCHEMA, V10DClosureError, run_v10d_closure
from eval_nagi_v10 import EXPECTED_CAPABILITIES

HAS_TORCH = importlib.util.find_spec("torch") is not None


class TestV10DClosureRunner(unittest.TestCase):
    def test_honest_blocked_status_when_torch_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            with patch("close_v10d.check_torch_cpu_runtime", return_value={"available": False, "reason": "No module named torch"}):
                result = run_v10d_closure(workspace_dir=ws)
            self.assertEqual(result["schema"], CLOSURE_RUNNER_SCHEMA)
            self.assertEqual(result["overall_status"], "BLOCKED")
            self.assertFalse(result["v11_unlocked"])
            self.assertEqual(result["v11_gate"]["status"], "LOCKED")
            self.assertIn("TORCH_NOT_INSTALLED", result["blockers"])
            self.assertFalse((ws / "checkpoints").exists())
            self.assertFalse((ws / "eval").exists())

    def test_rejects_resource_budget_violations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            with self.assertRaises(V10DClosureError):
                run_v10d_closure(workspace_dir=ws, batch_size=8)
            with self.assertRaises(V10DClosureError):
                run_v10d_closure(workspace_dir=ws, block_size=128)
            with self.assertRaises(V10DClosureError):
                run_v10d_closure(workspace_dir=ws, training_steps=501)
            with self.assertRaises(V10DClosureError):
                run_v10d_closure(workspace_dir=ws, cpu_threads=4)

    def test_end_to_end_v10d_closure_pipeline_with_hmac_approval_and_eval_gate(self) -> None:
        class _DummyCfg:
            def to_dict(self) -> dict:
                return {"vocab_size": 512, "max_seq_len": 256, "d_model": 256, "n_layers": 4, "n_heads": 4, "d_ff": 704}

        class _DummyModel:
            cfg = _DummyCfg()

        def _json_save(obj, path: str) -> None:
            Path(path).write_text(json.dumps(obj), encoding="utf-8")

        def _json_load(path: str):
            return json.loads(Path(path).read_text(encoding="utf-8"))

        def _fake_train_sft(model, train_pairs, val_pairs, cfg, checkpoint_dir, log_path, **kwargs):
            cm = CheckpointManager(checkpoint_dir, save_fn=_json_save, load_fn=_json_load)
            cm.save(
                cfg.max_steps,
                {
                    "model": {"w": [0.1, 0.2]},
                    "step": cfg.max_steps,
                    "tokenizer_sha256": kwargs.get("tokenizer_fingerprint"),
                    "dataset_version": kwargs.get("dataset_version") or "10.0.0",
                    "prompt_format": SFT_FORMAT_VERSION,
                    "model_config": model.cfg.to_dict(),
                },
            )
            return {
                "steps": cfg.max_steps,
                "epochs": 1.0,
                "train_loss": 0.42,
                "val_loss": 0.45,
                "perplexity": 1.568,
                "parameter_changed": True,
                "prompt_format": SFT_FORMAT_VERSION,
            }

        def _fake_eval_native(
            model_version: str,
            *,
            dataset_dir: Path,
            tokenizer_path: Path,
            checkpoint_dir: Path,
            registry_root: Path,
            max_examples: int | None,
            max_new_tokens: int,
        ) -> dict:
            cap_eval = {
                cap: {"status": "PASS", "accuracy": 0.85, "exact_match": 0.85, "correct": 17, "total": 20}
                for cap in EXPECTED_CAPABILITIES
            }
            return {
                "schema": "zyrquen.native_inference_evaluation.v1",
                "model_version": model_version,
                "tokenizer_sha256": "toksha",
                "inference_status": "PASS",
                "metrics": {"exact_match": 0.85, "eos_hit_rate": 1.0, "examples_evaluated": 20.0},
                "capability_evaluation": cap_eval,
            }

        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            counts = {"train": 18, "validation": 6, "test": 6}

            # 1. Without explicit admin approval -> must pause honestly at BLOCKED / WAITING_APPROVAL
            blocked_res = run_v10d_closure(
                workspace_dir=ws,
                counts=counts,
                vocab_size=320,
                training_steps=6,
                approve_training=False,
                _train_fn=_fake_train_sft,
                _eval_fn=_fake_eval_native,
                _model=_DummyModel(),
                _load_fn=_json_load,
            )
            self.assertEqual(blocked_res["overall_status"], "BLOCKED")
            self.assertIn("TIER2_HMAC_APPROVAL_REQUIRED", blocked_res["blockers"])
            self.assertFalse(blocked_res["v11_unlocked"])

        with tempfile.TemporaryDirectory() as td:
            ws2 = Path(td) / "ws2"
            counts = {"train": 18, "validation": 6, "test": 6}

            # 2. With explicit admin approval -> training + eval + registry + closure audit run end-to-end
            import close_v10d as _close_mod
            from apps.core.native.closure_audit import build_v10_closure_audit as _real_closure_audit

            orig_find_spec = importlib.util.find_spec

            def _find_spec_with_torch(name: str, *args, **kwargs):
                if name == "torch":
                    return object()
                return orig_find_spec(name, *args, **kwargs)

            def _closure_audit_with_torch(**kwargs):
                with patch("apps.core.native.closure_audit.importlib.util.find_spec", side_effect=_find_spec_with_torch):
                    return _real_closure_audit(**kwargs)

            with patch.object(_close_mod, "build_v10_closure_audit", side_effect=_closure_audit_with_torch):
                ok_res = run_v10d_closure(
                    workspace_dir=ws2,
                    counts=counts,
                    vocab_size=320,
                    training_steps=6,
                    approver_user_id="admin-01",
                    approver_role="admin",
                    approve_training=True,
                    _train_fn=_fake_train_sft,
                    _eval_fn=_fake_eval_native,
                    _model=_DummyModel(),
                    _load_fn=_json_load,
                )

            self.assertEqual(ok_res["overall_status"], "PASS", ok_res)
            self.assertTrue(ok_res["v11_unlocked"])
            self.assertEqual(ok_res["v11_gate"]["status"], "READY")
            self.assertEqual(ok_res["model_version"], "ZYRQUEN-Native-10.0.0")
            self.assertEqual(ok_res["lifecycle_status"], "verified")
            self.assertEqual(ok_res["training_workflow_status"], "COMPLETED")
            self.assertEqual(ok_res["evaluation_workflow_status"], "COMPLETED")
            self.assertTrue(Path(ok_res["eval_report_path"]).is_file())

            reg = ModelRegistry(Path(ok_res["paths"]["registry_root"]), load_fn=_json_load)
            self.assertTrue(reg.verify("ZYRQUEN-Native-10.0.0"))
            rec = reg.get("ZYRQUEN-Native-10.0.0")
            self.assertTrue(rec["evaluation_evidence"]["passed"])


if __name__ == "__main__":
    unittest.main()
