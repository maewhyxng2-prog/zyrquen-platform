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
            self.assertNotIn("MODEL_ARCHITECTURE_NOT_APPROVED", report["blockers"])
            self.assertNotIn("TRAINING_OBJECTIVE_NOT_APPROVED", report["blockers"])
            self.assertEqual(report["architecture"], "APPROVED")
            self.assertEqual(report["training_objective"], "APPROVED")
            self.assertTrue(
                "TIER2_HMAC_APPROVAL_REQUIRED" in report["blockers"]
                or "TIER2_APPROVAL_NOT_CONSUMED" in report["blockers"]
            )
            if not HAS_TORCH:
                self.assertIn("TORCH_NOT_INSTALLED", report["blockers"])

    def test_train_nagi_v10_with_tokenizer_path_forwards_payload_and_records_spec(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir = _make_valid_v10_dataset(root)
            train_rows = [json.loads(line) for line in (ds_dir / "train.jsonl").read_text().splitlines() if line.strip()]
            tok = train_slot_safe_tokenizer(train_rows, vocab_size=640, schema=SCHEMA_V2, use_slots=True)
            tok_path = root / "tokenizer.json"
            tok.save(tok_path)
            out_dir = root / "train_out"

            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "train_nagi_v10.py"),
                    "--dataset-dir",
                    str(ds_dir),
                    "--tokenizer-path",
                    str(tok_path),
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
            self.assertEqual(report["architecture"], "APPROVED")
            self.assertEqual(report["training_objective"], "APPROVED")
            self.assertEqual(report["architecture_spec"]["model_type"], "zyrquen-decoder")
            self.assertEqual(report["objective_spec"]["prompt_format"], SFT_FORMAT_VERSION)
            self.assertTrue(report["tokenizer"]["configured"])
            self.assertTrue(report["tokenizer"]["supports_atomic_slots"])
            self.assertEqual(report["tokenizer"]["tokenizer_sha256"], tok.fingerprint())
            self.assertFalse(report["training_started"])

    def test_eval_report_to_evaluation_gate_to_hmac_stage_and_promote_and_regression(self) -> None:
        tools_dir = str(REPO_ROOT / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        from eval_nagi_v10 import build_evaluation_report, build_regression_comparison, verify_dataset
        from apps.core.native.checkpoint import CheckpointManager
        from apps.core.native.config import ZyrquenConfig
        from apps.core.native.registry import ModelRegistry
        from apps.core.workflow.handlers.groups import handle_evaluation_gate
        from apps.core.workflow.models import WorkflowStepSpec
        from apps.core.workflow.orchestrator import CentralWorkflowOrchestrator

        def _json_save(obj: dict, path: str) -> None:
            Path(path).write_text(json.dumps(obj), encoding="utf-8")

        def _json_load(path: str) -> dict:
            return json.loads(Path(path).read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir = _make_valid_v10_dataset(root)
            ds_res = verify_dataset(ds_dir)
            train_rows = [json.loads(line) for line in (ds_dir / "train.jsonl").read_text().splitlines() if line.strip()]
            tok = train_slot_safe_tokenizer(train_rows, vocab_size=640, schema=SCHEMA_V2, use_slots=True)
            tok_path = root / "tokenizer.json"
            tok.save(tok_path)

            reg_root = root / "registry"
            reg = ModelRegistry(reg_root, load_fn=_json_load)
            orch = CentralWorkflowOrchestrator(db_path=root / "wf.db", work_dir=root, approval_secret="v10c-" * 8)
            try:
                model_cfg_dict = ZyrquenConfig(vocab_size=tok.vocab_size, max_seq_len=256).to_dict()
                run_id = orch.store.create_run(
                    workflow_key="lifecycle.v10c",
                    workflow_version="1.0.0",
                    trigger_type="manual",
                    trigger_payload={},
                    steps=[{"step_key": "gate", "depends_on": [], "lane": "governance"}],
                    requested_by_user_id="admin",
                )[0]["id"]

                def _mint_approved_token(tag: str, action_type: str, target_version: str) -> str:
                    step = WorkflowStepSpec(
                        step_key=f"step-{tag}",
                        handler_key="security.audit",
                        action_type=action_type,
                        lane="governance",
                        tier="tier2_approval",
                    )
                    pending = orch.governance.ensure_pending_approval(
                        run_id=run_id,
                        step=step,
                        requested_by_user_id="admin",
                        scope=f"model:{target_version}",
                    )
                    approved = orch.governance.decide_approval(
                        pending["id"], approve=True, approver_user_id="admin", approver_role="admin", reason="verified"
                    )
                    return approved["id"]

                # Register and promote baseline v10.0.0
                ckpt_base = root / "ckpt_base"
                cm_base = CheckpointManager(ckpt_base, save_fn=_json_save, load_fn=_json_load)
                cm_base.save(
                    100,
                    {
                        "step": 100,
                        "tokenizer_sha256": tok.fingerprint(),
                        "dataset_version": "10.0.0",
                        "prompt_format": SFT_FORMAT_VERSION,
                        "model_config": model_cfg_dict,
                    },
                )
                base_rec = reg.register(
                    "ZYRQUEN-Native-10.0.0",
                    ckpt_base,
                    tok_path,
                    ds_dir,
                    metrics={"exact_match": 0.70, "val_loss": 1.2},
                    capabilities={"abstract_reasoning": 0.70},
                    prompt_format=SFT_FORMAT_VERSION,
                )

                def _make_inf_result(score: float) -> dict:
                    caps = (
                        "abstract_reasoning",
                        "relational_generalization",
                        "ood_transfer",
                        "multi_step_planning",
                        "self_verification",
                        "knowledge_integration",
                    )
                    return {
                        "inference_status": "PASS",
                        "tokenizer_sha256": tok.fingerprint(),
                        "metrics": {
                            "exact_match": score,
                            "validation_exact_match": score,
                            "test_exact_match": score,
                            "eos_hit_rate": 1.0,
                            **{f"cap_{c}_accuracy": score for c in caps},
                        },
                        "capability_evaluation": {
                            c: {"status": "PASS", "accuracy": score, "correct": 8, "total": 10}
                            for c in caps
                        },
                    }

                base_eval = build_evaluation_report(
                    dataset_dir=ds_dir,
                    experiment_id="v10-base",
                    dataset_result=ds_res,
                    leakage_audit_status="PASS",
                    leakage_audit_detail={"status": "PASS"},
                    checkpoint_info={
                        "model_version": "ZYRQUEN-Native-10.0.0",
                        "checkpoint_sha256": base_rec["checkpoint"]["sha256"],
                        "verified": True,
                    },
                    inference_result=_make_inf_result(0.75),
                    inference_status="PASS",
                    regression_comparison=[],
                )
                self.assertEqual(base_eval["overall_status"], "PASS")
                base_report_path = root / "base_eval.json"
                base_report_path.write_text(json.dumps(base_eval), encoding="utf-8")

                gate_base = handle_evaluation_gate(
                    {"run_id": "run-base"},
                    {"report_path": str(base_report_path), "registry_root": str(reg_root), "model_version": "ZYRQUEN-Native-10.0.0"},
                )
                self.assertEqual(gate_base.verdict, "PASS", gate_base.summary)

                t_stage = _mint_approved_token("stage-base", "model.stage", "ZYRQUEN-Native-10.0.0")
                orch.stage_model_with_approval(reg, "ZYRQUEN-Native-10.0.0", approval_id=t_stage, actor_id="admin")
                t_prom = _mint_approved_token("prom-base", "model.promote", "ZYRQUEN-Native-10.0.0")
                orch.promote_model_with_approval(reg, "ZYRQUEN-Native-10.0.0", approval_id=t_prom, actor_id="admin")
                self.assertEqual(reg.active_version(), "ZYRQUEN-Native-10.0.0")

                # Candidate v10.1.0 with zero regression -> PASS gate -> stage -> promote
                ckpt_cand = root / "ckpt_cand"
                cm_cand = CheckpointManager(ckpt_cand, save_fn=_json_save, load_fn=_json_load)
                cm_cand.save(
                    200,
                    {
                        "step": 200,
                        "tokenizer_sha256": tok.fingerprint(),
                        "dataset_version": "10.0.0",
                        "prompt_format": SFT_FORMAT_VERSION,
                        "model_config": model_cfg_dict,
                    },
                )
                cand_rec = reg.register(
                    "ZYRQUEN-Native-10.1.0",
                    ckpt_cand,
                    tok_path,
                    ds_dir,
                    metrics={"exact_match": 0.85, "val_loss": 0.9},
                    capabilities={"abstract_reasoning": 0.85},
                    parent="ZYRQUEN-Native-10.0.0",
                    prompt_format=SFT_FORMAT_VERSION,
                )
                cand_inf = _make_inf_result(0.85)
                cand_reg_cmp = build_regression_comparison(reg_root, "ZYRQUEN-Native-10.1.0", cand_inf)
                self.assertTrue(cand_reg_cmp and cand_reg_cmp[0]["zero_regression"])
                cand_eval = build_evaluation_report(
                    dataset_dir=ds_dir,
                    experiment_id="v10-cand",
                    dataset_result=ds_res,
                    leakage_audit_status="PASS",
                    leakage_audit_detail={"status": "PASS"},
                    checkpoint_info={
                        "model_version": "ZYRQUEN-Native-10.1.0",
                        "checkpoint_sha256": cand_rec["checkpoint"]["sha256"],
                        "verified": True,
                    },
                    inference_result=cand_inf,
                    inference_status="PASS",
                    regression_comparison=cand_reg_cmp,
                )
                cand_report_path = root / "cand_eval.json"
                cand_report_path.write_text(json.dumps(cand_eval), encoding="utf-8")
                gate_cand = handle_evaluation_gate(
                    {"run_id": "run-cand"},
                    {"report_path": str(cand_report_path), "registry_root": str(reg_root), "model_version": "ZYRQUEN-Native-10.1.0"},
                )
                self.assertEqual(gate_cand.verdict, "PASS", gate_cand.summary)

                t_stage2 = _mint_approved_token("stage-cand", "model.stage", "ZYRQUEN-Native-10.1.0")
                orch.stage_model_with_approval(reg, "ZYRQUEN-Native-10.1.0", approval_id=t_stage2, actor_id="admin")
                t_prom2 = _mint_approved_token("prom-cand", "model.promote", "ZYRQUEN-Native-10.1.0")
                orch.promote_model_with_approval(reg, "ZYRQUEN-Native-10.1.0", approval_id=t_prom2, actor_id="admin")
                self.assertEqual(reg.active_version(), "ZYRQUEN-Native-10.1.0")

                # Regressed inference against active 10.1.0 (0.85 -> 0.50) must fail regression check
                regressed_cmp = build_regression_comparison(reg_root, "ZYRQUEN-Native-10.0.0", _make_inf_result(0.50))
                self.assertFalse(regressed_cmp[0]["zero_regression"])
            finally:
                orch.shutdown(wait=True)

    def test_compare_and_diagnose_work_on_real_eval_nagi_v10_schemas(self) -> None:
        tools_dir = str(REPO_ROOT / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        from compare_nagi_v10 import build_entry, build_result
        from diagnose_nagi_v10 import build_diagnosis
        from eval_nagi_v10 import build_evaluation_report, verify_dataset

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ds_dir = _make_valid_v10_dataset(root)
            ds_res = verify_dataset(ds_dir)

            # 1. Default NOT RUN report -> diagnose must report NOT READY
            not_run_rep = build_evaluation_report(
                dataset_dir=ds_dir,
                experiment_id="v10-not-run",
                dataset_result=ds_res,
                leakage_audit_status="PASS",
                leakage_audit_detail={"status": "PASS"},
                checkpoint_info=None,
            )
            diag_not_run = build_diagnosis(root / "nr.json", not_run_rep)
            self.assertEqual(diag_not_run["overall_status"], "NOT READY")

            # 2. Two PASS reports with real EvaluationEngine metric keys -> compare COMPARABLE & diagnose READY_FOR_REVIEW
            caps = (
                "abstract_reasoning",
                "relational_generalization",
                "ood_transfer",
                "multi_step_planning",
                "self_verification",
                "knowledge_integration",
            )
            rep_a = build_evaluation_report(
                dataset_dir=ds_dir,
                experiment_id="v10-a",
                dataset_result=ds_res,
                leakage_audit_status="PASS",
                leakage_audit_detail={"status": "PASS"},
                checkpoint_info=None,
                inference_status="PASS",
                inference_result={
                    "metrics": {"exact_match": 0.65, "validation_exact_match": 0.6, "test_exact_match": 0.7, "eos_hit_rate": 1.0, **{f"cap_{c}_accuracy": 0.65 for c in caps}},
                    "capability_evaluation": {c: {"status": "PASS", "accuracy": 0.65} for c in caps},
                },
            )
            rep_b = build_evaluation_report(
                dataset_dir=ds_dir,
                experiment_id="v10-b",
                dataset_result=ds_res,
                leakage_audit_status="PASS",
                leakage_audit_detail={"status": "PASS"},
                checkpoint_info=None,
                inference_status="PASS",
                inference_result={
                    "metrics": {"exact_match": 0.85, "validation_exact_match": 0.8, "test_exact_match": 0.9, "eos_hit_rate": 1.0, **{f"cap_{c}_accuracy": 0.85 for c in caps}},
                    "capability_evaluation": {c: {"status": "PASS", "accuracy": 0.85} for c in caps},
                },
            )
            diag_pass = build_diagnosis(root / "b.json", rep_b)
            self.assertEqual(diag_pass["overall_status"], "READY_FOR_REVIEW")

            cmp_out = build_result([build_entry(root / "v10_evaluation_a.json", rep_a), build_entry(root / "v10_evaluation_b.json", rep_b)])
            self.assertEqual(cmp_out["overall_status"], "COMPARISON_AVAILABLE")
            self.assertEqual(cmp_out["comparison"]["metric_comparisons"]["exact_match"]["status"], "COMPARABLE")
            self.assertEqual(cmp_out["comparison"]["metric_comparisons"]["test_exact_match"]["ranked_results"][0]["report"], "v10_evaluation_b.json")


if __name__ == "__main__":
    unittest.main()
