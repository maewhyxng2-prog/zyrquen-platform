"""V10-B Evaluation Gate Safety, False-PASS Closure, Registry Hardening, and v10 Leakage Dispatch tests."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.core.native.config import ZyrquenConfig
from apps.core.native.dataset import PrepConfig, Source, prepare_dataset
from apps.core.native.registry import ModelRegistry, RegistryError
from apps.core.native.tokenizer import BASE_VOCAB, ZyrquenTokenizer
from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager
from apps.core.workflow import ApprovalViolationError
from apps.core.workflow.governance import WorkflowGovernance
from apps.core.workflow.handlers.groups import handle_data_verify_and_audit, handle_evaluation_gate
from apps.core.workflow.models import LeakageGateFailedError, WorkflowStepSpec
from apps.core.workflow.store import WorkflowStore


def _json_save(obj, path: str) -> None:
    Path(path).write_text(json.dumps(obj), encoding="utf-8")


def _json_load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _create_dummy_registry_and_version(root: Path, version: str = "ZYRQUEN-Native-0.1.0") -> tuple[ModelRegistry, dict]:
    docs = [{"text": f"native logic verify test sample {i} reasoning planning"} for i in range(40)]
    src = root / "corpus.jsonl"
    src.write_text("\n".join(json.dumps(d) for d in docs), encoding="utf-8")
    ds_dir = root / "dataset"
    prepare_dataset([Source(str(src), "apache-2.0")], ds_dir, PrepConfig(val_fraction=0.1, test_fraction=0.1, version="1.0.0"))

    tok = ZyrquenTokenizer.train([d["text"] for d in docs], BASE_VOCAB + 16, version="1.0.0")
    tok_path = root / "tokenizer.json"
    tok.save(tok_path)

    cfg = ZyrquenConfig(vocab_size=tok.vocab_size, d_ff=704)
    ckpt_dir = root / "ckpts"
    CheckpointManager(ckpt_dir, save_fn=_json_save, load_fn=_json_load).save(
        10,
        {
            "step": 10,
            "tokenizer_sha256": tok.fingerprint(),
            "dataset_version": "1.0.0",
            "model_config": cfg.to_dict(),
            "config": {"max_steps": 10},
        },
    )
    reg = ModelRegistry(root / "registry", load_fn=_json_load)
    rec = reg.register(version, ckpt_dir, tok_path, ds_dir)
    return reg, rec


def _valid_v10_report(ckpt_sha256: str, version: str = "ZYRQUEN-Native-0.1.0") -> dict:
    return {
        "schema_version": "1.0",
        "report_schema": "zyrquen.v10.evaluation_report.v1",
        "experiment_id": "v10-unit-eval",
        "overall_status": "PASS",
        "dataset_integrity": "PASS",
        "leakage_audit_status": "PASS",
        "inference_status": "PASS",
        "inference_hook_implemented": True,
        "capability_evaluation": {
            "abstract_reasoning": {"status": "PASS", "exact_match": 0.88},
            "relational_generalization": {"status": "PASS", "exact_match": 0.86},
            "ood_transfer": {"status": "PASS", "exact_match": 0.82},
            "multi_step_planning": {"status": "PASS", "exact_match": 0.84},
            "self_verification": {"status": "PASS", "exact_match": 0.90},
            "knowledge_integration": {"status": "PASS", "exact_match": 0.85},
        },
        "metrics": {
            "test_exact_match": 0.86,
            "validation_exact_match": 0.89,
            "eos_hit_rate": 0.99,
        },
        "checkpoint": {
            "model_version": version,
            "checkpoint_sha256": ckpt_sha256,
            "verified": True,
        },
        "acceptance_assessment": {
            "criteria": {"exact_match_ge_0.80": {"status": "PASS"}},
            "stop_criteria_triggered": [],
        },
        "regression_comparison": [],
        "error": None,
    }


def _valid_v9_report() -> dict:
    return {
        "schema_version": "zyrquen.eval-v9.report.v1",
        "data_integrity": {"leakage_audit_status": "PASS"},
        "splits": {
            "test_unseen": {"overall": {"free_generation": {"exact_match": 0.91, "unseen_entity_copy_acc": 0.95}}},
            "test_ood": {"overall": {"free_generation": {"exact_match": 0.83}}},
        },
        "acceptance_assessment": {
            "criteria": {
                "overall_exact_match": {"status": "PASS"},
                "pointer_gate_discipline": {"status": "NOT_APPLICABLE"},
                "beats_baselines_ood_by_5pp": {"status": "PENDING_COMPARISON"},
            },
            "stop_criteria_triggered": [],
        },
        "regression_comparison": [],
    }


def _write_v10_dataset(dataset_dir: Path, *, leak_entity: bool = False) -> None:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    def _row(eid: str, split: str, ent1: str, ent2: str, tmpl: str, phrasing: str):
        inp = f"{phrasing}: {ent1} -> {ent2} ?"
        return {
            "schema_version": "1.0",
            "example_id": eid,
            "split": split,
            "capability": "relational_generalization",
            "task_type": "edge_query",
            "reasoning_operator": f"op_{split}",
            "template_id": tmpl,
            "instruction": phrasing,
            "input": inp,
            "target": ent2,
            "facts": [{"relation": "edge", "source": ent1, "target": ent2}],
            "query": {"relation": "edge", "source": ent1, "hops": 1},
            "answer": ent2,
            "unique_answer_verified": True,
            "metadata": {"source": "unit"},
        }

    bad_test_ent = "TR_E101" if leak_entity else "TE_E301"
    splits = {
        "train": [_row("ex_tr_1", "train", "TR_E101", "TR_E102", "tpl_train", "Direct link trace")],
        "validation": [_row("ex_va_1", "validation", "VA_E201", "VA_E202", "tpl_val", "Validation hop inspect")],
        "test": [_row("ex_te_1", "test", bad_test_ent, "TE_E302", "tpl_test", "OOD unseen deduction")],
    }
    files = {}
    for s, rows in splits.items():
        p = dataset_dir / f"{s}.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        files[f"{s}.jsonl"] = {
            "path": f"{s}.jsonl",
            "documents": len(rows),
            "sha256": _sha256_bytes(p.read_bytes()),
        }

    content_hash = hashlib.sha256(
        "".join(files[f"{s}.jsonl"]["sha256"] for s in ("train", "validation", "test")).encode()
    ).hexdigest()
    manifest = {
        "schema": "zyrquen.dataset-manifest.v1",
        "dataset": "nagi_v10",
        "version": "10.0.0",
        "content_sha256": content_hash,
        "files": files,
    }
    (dataset_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class TestEvaluationGateFalsePassClosure(unittest.TestCase):
    def test_missing_symlink_malformed_and_empty_reports_rejected(self):
        ctx = {"run_id": "run-1"}
        # Missing path -> NOT RUN
        res = handle_evaluation_gate(ctx, {})
        self.assertEqual(res.verdict, "NOT RUN")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Non-existent file -> NOT RUN
            res_missing = handle_evaluation_gate(ctx, {"report_path": str(root / "does_not_exist.json")})
            self.assertEqual(res_missing.verdict, "NOT RUN")

            # Empty {} object -> FAIL (unsupported_eval_schema, never False-PASS!)
            empty_path = root / "empty.json"
            empty_path.write_text("{}", encoding="utf-8")
            res_empty = handle_evaluation_gate(ctx, {"report_path": str(empty_path)})
            self.assertEqual(res_empty.verdict, "FAIL")
            self.assertEqual(res_empty.error_code, "unsupported_eval_schema")

            # Malformed JSON -> FAIL
            bad_json = root / "bad.json"
            bad_json.write_text("{broken", encoding="utf-8")
            res_bad = handle_evaluation_gate(ctx, {"report_path": str(bad_json)})
            self.assertEqual(res_bad.verdict, "FAIL")
            self.assertEqual(res_bad.error_code, "malformed_eval_report")

            # Symlink -> BLOCKED
            sym = root / "link.json"
            sym.symlink_to(empty_path)
            res_sym = handle_evaluation_gate(ctx, {"report_path": str(sym)})
            self.assertEqual(res_sym.verdict, "BLOCKED")
            self.assertEqual(res_sym.error_code, "symlink_eval_report")

    def test_v10_not_run_blocked_and_false_pass_cannot_verify_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reg, rec = _create_dummy_registry_and_version(root)
            ckpt_sha = rec["checkpoint"]["sha256"]

            # 1. Real v10 NOT RUN report -> NOT RUN, lifecycle stays 'registered'
            not_run = _valid_v10_report(ckpt_sha)
            not_run["overall_status"] = "NOT RUN"
            not_run["inference_status"] = "NOT RUN"
            not_run["inference_hook_implemented"] = False
            not_run["capability_evaluation"] = {k: "NOT RUN" for k in not_run["capability_evaluation"]}
            not_run["metrics"] = None
            p1 = root / "v10_not_run.json"
            p1.write_text(json.dumps(not_run), encoding="utf-8")
            r1 = handle_evaluation_gate(
                {"run_id": "run-not-run"},
                {"report_path": str(p1), "registry_root": str(reg.root), "model_version": rec["version"]},
            )
            self.assertEqual(r1.verdict, "NOT RUN")
            self.assertEqual(reg.get(rec["version"])["lifecycle_status"], "registered")

            # 2. False-PASS attempt: overall=PASS, hook=True, metrics present, but one capability="NOT RUN"
            false_pass = _valid_v10_report(ckpt_sha)
            false_pass["capability_evaluation"]["ood_transfer"] = "NOT RUN"
            p2 = root / "v10_false_pass.json"
            p2.write_text(json.dumps(false_pass), encoding="utf-8")
            r2 = handle_evaluation_gate(
                {"run_id": "run-fp"},
                {"report_path": str(p2), "registry_root": str(reg.root), "model_version": rec["version"]},
            )
            self.assertEqual(r2.verdict, "FAIL")
            self.assertEqual(reg.get(rec["version"])["lifecycle_status"], "quarantined")

            # 3. Wrong checkpoint SHA-256 -> FAIL & quarantined
            wrong_sha = _valid_v10_report("0" * 64)
            p3 = root / "v10_wrong_sha.json"
            p3.write_text(json.dumps(wrong_sha), encoding="utf-8")
            r3 = handle_evaluation_gate(
                {"run_id": "run-sha"},
                {"report_path": str(p3), "registry_root": str(reg.root), "model_version": rec["version"]},
            )
            self.assertEqual(r3.verdict, "FAIL")
            self.assertEqual(reg.get(rec["version"])["lifecycle_status"], "quarantined")

            # 4. Valid v10 PASS report -> PASS, verified, compatible, promotable
            valid = _valid_v10_report(ckpt_sha)
            p4 = root / "v10_pass.json"
            p4.write_text(json.dumps(valid), encoding="utf-8")
            r4 = handle_evaluation_gate(
                {"run_id": "run-pass"},
                {"report_path": str(p4), "registry_root": str(reg.root), "model_version": rec["version"]},
            )
            self.assertEqual(r4.verdict, "PASS")
            self.assertEqual(reg.get(rec["version"])["lifecycle_status"], "verified")
            self.assertTrue(reg.check_compatibility(rec["version"], expected_model_type="zyrquen-decoder")["compatible"])

            reg.set_lifecycle_status(rec["version"], "staging", approval_id="app-stg")
            reg.promote(rec["version"], enforce_evaluation_gate=True, approval_id="app-prod")
            self.assertEqual(reg.active_version(), rec["version"])
            self.assertEqual(reg.get(rec["version"])["lifecycle_status"], "production")

    def test_v9_missing_stop_triggers_and_empty_criteria_rejected_and_valid_v9_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reg, rec = _create_dummy_registry_and_version(root)

            # Missing stop_criteria_triggered & empty criteria -> FAIL
            bad_v9 = _valid_v9_report()
            del bad_v9["acceptance_assessment"]["stop_criteria_triggered"]
            bad_v9["acceptance_assessment"]["criteria"] = {}
            p_bad = root / "v9_bad.json"
            p_bad.write_text(json.dumps(bad_v9), encoding="utf-8")
            r_bad = handle_evaluation_gate(
                {"run_id": "run-v9-bad"},
                {"report_path": str(p_bad), "registry_root": str(reg.root), "model_version": rec["version"]},
            )
            self.assertEqual(r_bad.verdict, "FAIL")
            self.assertEqual(reg.get(rec["version"])["lifecycle_status"], "quarantined")

            # Valid v9 PASS -> PASS & verified
            good_v9 = _valid_v9_report()
            p_good = root / "v9_good.json"
            p_good.write_text(json.dumps(good_v9), encoding="utf-8")
            r_good = handle_evaluation_gate(
                {"run_id": "run-v9-good"},
                {"report_path": str(p_good), "registry_root": str(reg.root), "model_version": rec["version"]},
            )
            self.assertEqual(r_good.verdict, "PASS")
            self.assertEqual(reg.get(rec["version"])["lifecycle_status"], "verified")

    def test_registry_direct_certification_and_baseline_bypasses_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reg, rec = _create_dummy_registry_and_version(root)
            ver = rec["version"]

            # Direct set_lifecycle_status -> verified / production / staging blocked
            with self.assertRaises(RegistryError):
                reg.set_lifecycle_status(ver, "verified")
            with self.assertRaises(RegistryError):
                reg.set_lifecycle_status(ver, "production")
            with self.assertRaises(RegistryError):
                reg.set_lifecycle_status(ver, "staging")

            # Empty metrics / non-hex sha / NOT RUN status rejected in attach_evaluation_evidence(passed=True)
            with self.assertRaises(RegistryError):
                reg.attach_evaluation_evidence(
                    ver, eval_run_id="e1", report_sha256="short", metrics={"a": 1.0}, passed=True, zero_regression=True
                )
            with self.assertRaises(RegistryError):
                reg.attach_evaluation_evidence(
                    ver, eval_run_id="e1", report_sha256="a" * 64, metrics={}, passed=True, zero_regression=True
                )
            with self.assertRaises(RegistryError):
                reg.attach_evaluation_evidence(
                    ver,
                    eval_run_id="e1",
                    report_sha256="a" * 64,
                    metrics={"acc": 0.9},
                    passed=True,
                    zero_regression=True,
                    evaluation_status="NOT RUN",
                )
            with self.assertRaises(RegistryError):
                reg.attach_evaluation_evidence(
                    ver,
                    eval_run_id="e1",
                    report_sha256="a" * 64,
                    metrics={"acc": 0.9},
                    passed=True,
                    zero_regression=True,
                    inference_executed=False,
                )

            # Protected frozen baselines v7/v8/v9 cannot be overwritten
            for frozen_name in ("v7", "v8", "v9", "ZYRQUEN-v9"):
                with self.assertRaises(RegistryError):
                    reg.register(frozen_name, root / "ckpts", root / "tokenizer.json", root / "dataset")

    def test_v10_data_audit_dispatch_passes_clean_and_blocks_leakage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean_ds = root / "clean_v10"
            _write_v10_dataset(clean_ds, leak_entity=False)
            res_ok = handle_data_verify_and_audit({}, {"dataset_dir": str(clean_ds)})
            self.assertEqual(res_ok.verdict, "PASS")
            self.assertIn("v10 Data Leakage", res_ok.summary)

            leaked_ds = root / "leaked_v10"
            _write_v10_dataset(leaked_ds, leak_entity=True)
            with self.assertRaises(LeakageGateFailedError):
                handle_data_verify_and_audit({}, {"dataset_dir": str(leaked_ds)})

    def test_governance_verify_and_consume_by_id_single_use_and_hmac(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "wf.db")
            gov = WorkflowGovernance(store, secret="test-secret-key-at-least-32-chars!!")
            run_id = store.create_run(
                workflow_key="training.native",
                workflow_version="1.0.0",
                trigger_type="manual",
                trigger_payload={},
                steps=[{"step_key": "execute_training", "depends_on": [], "lane": "training"}],
                requested_by_user_id="u-1",
            )[0]["id"]
            step = WorkflowStepSpec(
                step_key="execute_training",
                handler_key="training.execute",
                action_type="training.execute",
                lane="training",
                tier="tier2_approval",
            )
            pending = gov.ensure_pending_approval(run_id=run_id, step=step, requested_by_user_id="u-1", scope="train")
            approved = gov.decide_approval(
                pending["id"], approve=True, approver_user_id="admin-1", approver_role="admin", reason="ok"
            )
            # Wrong action type fails
            with self.assertRaises(ApprovalViolationError):
                gov.verify_and_consume_by_id(approved["id"], expected_action_type="model.promote")

            # Valid single-use consumption succeeds once, second attempt fails
            consumed = gov.verify_and_consume_by_id(approved["id"], expected_action_type="training.execute")
            self.assertEqual(consumed["status"], "consumed")
            with self.assertRaises(ApprovalViolationError):
                gov.verify_and_consume_by_id(approved["id"], expected_action_type="training.execute")


if __name__ == "__main__":
    unittest.main()
