"""Tests for V10 Final Closure Audit service (pure stdlib unittest)."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.core.native.closure_audit import CLOSURE_AUDIT_SCHEMA, build_v10_closure_audit
from apps.core.native.checkpoint import CheckpointManager
from apps.core.native.config import ZyrquenConfig
from apps.core.native.dataset import SCHEMA as DATASET_SCHEMA
from apps.core.native.registry import ModelRegistry
from apps.core.native.sft import SFT_FORMAT_VERSION, train_slot_safe_tokenizer
from apps.core.native.tokenizer import SCHEMA_V2

HAS_TORCH = importlib.util.find_spec("torch") is not None


class TestV10ClosureAudit(unittest.TestCase):
    def test_contracts_1_to_5_verify_from_real_modules_and_v11_remains_locked_without_runtime(self) -> None:
        audit = build_v10_closure_audit(
            eval_report_path="",
            registry_root="",
            dataset_dir="",
            tokenizer_path="",
            runtime_health={
                "runtime_status": "not_configured",
                "native_model_loaded": False,
                "is_trained": False,
                "model_version": None,
            },
        )
        self.assertEqual(audit["schema"], CLOSURE_AUDIT_SCHEMA)
        self.assertEqual(audit["contracts_passed_count"], 5)
        self.assertEqual(audit["contracts_total"], 5)
        self.assertEqual(audit["static_status"], "STATIC PASS")
        for contract in audit["contracts"]:
            self.assertEqual(contract["status"], "STATIC PASS", contract)

        # Must NEVER unlock V11 or fabricate PASS without real trained checkpoint + passing eval report
        self.assertFalse(audit["v11_gate"]["unlocked"])
        self.assertEqual(audit["v11_gate"]["status"], "LOCKED")
        self.assertIn("EVAL_REPORT_NOT_CONFIGURED", audit["blockers"])
        self.assertIn("TRAINED_V10_MODEL_UNAVAILABLE", audit["blockers"])
        if not HAS_TORCH:
            self.assertEqual(audit["runtime_status"], "BLOCKED")
            self.assertEqual(audit["overall_status"], "BLOCKED")
            self.assertIn("TORCH_NOT_INSTALLED", audit["blockers"])
        else:
            self.assertEqual(audit["runtime_status"], "NOT RUN")
            self.assertEqual(audit["overall_status"], "NOT RUN")

    def test_blocked_or_not_run_eval_report_never_marks_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report_path = root / "eval_not_run.json"
            report_path.write_text(
                json.dumps({
                    "report_schema": "zyrquen.v10.evaluation_report.v1",
                    "overall_status": "NOT RUN",
                    "inference_status": "NOT RUN",
                    "dataset_integrity": "PASS",
                    "leakage_audit_status": "PASS",
                }),
                encoding="utf-8",
            )
            audit = build_v10_closure_audit(
                eval_report_path=report_path,
                registry_root="",
                dataset_dir="",
                tokenizer_path="",
                runtime_health={"runtime_status": "not_configured", "native_model_loaded": False, "is_trained": False},
            )
            self.assertFalse(audit["v11_gate"]["unlocked"])
            self.assertEqual(audit["v11_gate"]["status"], "LOCKED")
            self.assertNotEqual(audit["overall_status"], "PASS")

    def test_symlinked_eval_report_is_rejected_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            real_report = root / "real.json"
            real_report.write_text(
                json.dumps({
                    "report_schema": "zyrquen.v10.evaluation_report.v1",
                    "overall_status": "PASS",
                    "inference_status": "PASS",
                    "dataset_integrity": "PASS",
                    "leakage_audit_status": "PASS",
                }),
                encoding="utf-8",
            )
            link_report = root / "link.json"
            link_report.symlink_to(real_report)

            audit = build_v10_closure_audit(
                eval_report_path=link_report,
                registry_root="",
                runtime_health={"runtime_status": "not_configured", "native_model_loaded": False, "is_trained": False},
            )
            self.assertFalse(audit["v11_gate"]["unlocked"])
            self.assertIn("EVAL_REPORT_INVALID_PATH", audit["blockers"])

    def test_verified_registry_plus_passing_eval_report_reports_accurate_eval_state(self) -> None:
        def _json_save(obj, path: str) -> None:
            Path(path).write_text(json.dumps(obj), encoding="utf-8")

        def _json_load(path: str):
            return json.loads(Path(path).read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir = root / "ds"
            ds_dir.mkdir()
            rows = [{"input": "TR_E1 -> TR_E2", "target": "TR_E2"}]
            for split in ("train", "validation", "test"):
                (ds_dir / f"{split}.jsonl").write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
            import hashlib
            files = {
                f"{s}.jsonl": {
                    "documents": 1,
                    "sha256": hashlib.sha256((ds_dir / f"{s}.jsonl").read_bytes()).hexdigest(),
                }
                for s in ("train", "validation", "test")
            }
            content_sha = hashlib.sha256(
                "".join(files[f"{s}.jsonl"]["sha256"] for s in ("train", "validation", "test")).encode()
            ).hexdigest()
            (ds_dir / "manifest.json").write_text(
                json.dumps({
                    "schema": DATASET_SCHEMA,
                    "version": "10.0.0",
                    "content_sha256": content_sha,
                    "sources": {"nagi_v10": {"path": "synthetic://test", "license": "internal", "sha256": "a" * 64}},
                    "files": files,
                }),
                encoding="utf-8",
            )

            tok = train_slot_safe_tokenizer(rows * 5, vocab_size=320, schema=SCHEMA_V2, use_slots=True)
            tok_path = root / "tok.json"
            tok.save(tok_path)

            ckpt_dir = root / "ckpt"
            cm = CheckpointManager(ckpt_dir, save_fn=_json_save, load_fn=_json_load)
            cfg = ZyrquenConfig(vocab_size=tok.vocab_size, d_ff=704).to_dict()
            cm.save(10, {"model": {"w": [1]}, "step": 10, "tokenizer_sha256": tok.fingerprint(), "dataset_version": "10.0.0", "prompt_format": SFT_FORMAT_VERSION, "model_config": cfg})

            reg = ModelRegistry(root / "reg", load_fn=_json_load)
            rec = reg.register("ZYRQUEN-Native-10.0.0", ckpt_dir, tok_path, ds_dir, prompt_format=SFT_FORMAT_VERSION)

            report_path = root / "eval_pass.json"
            report_payload = {
                "report_schema": "zyrquen.v10.evaluation_report.v1",
                "overall_status": "PASS",
                "inference_status": "PASS",
                "dataset_integrity": "PASS",
                "leakage_audit_status": "PASS",
                "regression_comparison": [{"zero_regression": True}],
            }
            report_path.write_text(json.dumps(report_payload), encoding="utf-8")
            import hashlib as hl
            reg.attach_evaluation_evidence(
                "ZYRQUEN-Native-10.0.0",
                metrics={"exact_match": 0.9},
                report_sha256=hl.sha256(report_path.read_bytes()).hexdigest(),
                eval_run_id="eval-1",
                passed=True,
                zero_regression=True,
                evaluation_status="PASS",
                inference_executed=True,
                report_schema="zyrquen.v10.evaluation_report.v1",
            )

            audit = build_v10_closure_audit(
                eval_report_path=report_path,
                registry_root=root / "reg",
                dataset_dir=ds_dir,
                tokenizer_path=tok_path,
                runtime_health={"runtime_status": "ready", "native_model_loaded": True, "is_trained": True, "model_version": "ZYRQUEN-Native-10.0.0"},
            )
            self.assertEqual(audit["runtime_environment"]["verified_v10_models"], 1)
            self.assertTrue(audit["runtime_environment"]["eval_report_configured"])
            if HAS_TORCH:
                self.assertEqual(audit["overall_status"], "PASS")
                self.assertTrue(audit["v11_gate"]["unlocked"])
            else:
                # Without torch, runtime closure MUST still stay BLOCKED and V11 LOCKED
                self.assertEqual(audit["overall_status"], "BLOCKED")
                self.assertFalse(audit["v11_gate"]["unlocked"])


if __name__ == "__main__":
    unittest.main()
